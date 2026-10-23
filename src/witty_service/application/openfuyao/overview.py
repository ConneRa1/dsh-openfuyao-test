"""PolyMind 对 openFuyao 控制台的“感知层”。

控制台创建的业务集群、应用市场/Helm 安装的 release 不会经过 witty-service 的
创建 API，因此数据库里的 ``openfuyao_clusters`` / ``openfuyao_apps`` 只能算
“本服务创建过的对象”。本模块每次刷新时读取：

- 管理面 ``BKECluster`` / ``BKENode``（用户在引导节点控制台创建的集群）；
- 业务集群的 Helm release（用户在业务控制台/命令行安装的应用）；
- 业务 Pod 的等待原因（镜像拉取失败、CrashLoop、Pending 等）。

发现结果会**按名称幂等纳管**到数据库，并生成可执行建议（``OverviewIssue``）。
这样后续自然语言安装/回滚可以直接复用 ``app install`` / ``app rollback``，
而不是只显示一个只读快照。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from witty_service.application.openfuyao.cluster_spec import NodeSpec
from witty_service.application.openfuyao.console_health import (
    ConsoleSessionProbe,
    build_console_url,
    probe_console_session,
)
from witty_service.application.openfuyao.helm import HelmClient, HelmError, HelmRelease
from witty_service.application.openfuyao.kube import ConsoleEndpoint, KubeClient
from witty_service.application.openfuyao.preflight import detect_host_ip
from witty_service.application.openfuyao.process import CommandRunner
from witty_service.config import OpenFuyaoSettings
from witty_service.domain.openfuyao import (
    APP_ACTIVE_STATUSES,
    CLUSTER_ACTIVE_STATUSES,
    AppStatus,
    ClusterStatus,
    NodeRole,
    NodeStatus,
)
from witty_service.persistence.openfuyao_cluster_repository import (
    AppRecord,
    ClusterRecord,
    OpenFuyaoClusterRepository,
)
from witty_service.persistence.openfuyao_repository import OpenFuyaoRepository

__all__ = [
    "ObservedOverview",
    "OpenFuyaoObserver",
    "OverviewIssue",
]

#: 平台自身的 release 不是用户应用，避免把控制台依赖混进“已安装应用”。
_PLATFORM_NAMESPACES = frozenset(
    {
        "openfuyao-system",
        "kube-system",
        "kube-public",
        "kube-node-lease",
        "cluster-system",
        "ingress-nginx",
        "openfuyao-patch",
        "bke-containerd",
        "bke-kubelet",
        "session-secret",
        "oauth-code-token",
    }
)

_IMAGE_PULL_REASONS = frozenset(
    {"ImagePullBackOff", "ErrImagePull", "InvalidImageName", "ImageInspectError"}
)
_CRASH_REASONS = frozenset(
    {"CrashLoopBackOff", "RunContainerError", "CreateContainerError"}
)


@dataclass(frozen=True, slots=True)
class OverviewIssue:
    """一条可展示、可执行的诊断结论。"""

    code: str
    severity: str
    source: str
    title: str
    message: str
    remediation: str = ""
    resource_id: str | None = None
    resource_name: str | None = None

    @property
    def id(self) -> str:
        return (
            f"{self.source}:{self.resource_id or self.resource_name or '-'}:{self.code}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "code": self.code,
            "severity": self.severity,
            "source": self.source,
            "title": self.title,
            "message": self.message,
            "remediation": self.remediation,
            "resource_id": self.resource_id,
            "resource_name": self.resource_name,
        }


@dataclass(frozen=True, slots=True)
class ObservedOverview:
    clusters: tuple[ClusterRecord, ...]
    apps: tuple[AppRecord, ...]
    issues: tuple[OverviewIssue, ...]
    console: ConsoleEndpoint
    refreshed_at: str
    errors: tuple[str, ...] = ()
    discovered: bool = True
    #: 引导节点控制台的 Cookie 透传探测；为空表示没有可探测的环境。
    guide_console: ConsoleSessionProbe | None = None


class OpenFuyaoObserver:
    def __init__(
        self,
        *,
        repository: OpenFuyaoClusterRepository,
        environment_repository: OpenFuyaoRepository,
        settings: OpenFuyaoSettings,
        workspace_root: Path,
        local_ip: str | None = None,
    ) -> None:
        self._repository = repository
        self._environments = environment_repository
        self._settings = settings
        self._work_dir = (
            Path(settings.work_dir)
            if settings.work_dir
            else (workspace_root / "openfuyao")
        )
        self._local_ip = local_ip or settings.host or detect_host_ip()
        self._lock = asyncio.Lock()

    async def refresh(self, agent_id: str) -> ObservedOverview:
        """读控制台资源并纳管；失败时退回数据库快照，不阻塞面板。"""
        if not self._settings.console_discovery:
            return self._snapshot(
                agent_id,
                discovered=False,
                errors=("console_discovery_disabled",),
                console=ConsoleEndpoint(reason="discovery_disabled"),
            )
        async with self._lock:
            errors: list[str] = []
            commands = CommandRunner(cwd=self._work_dir, log=lambda _line: None)
            client = KubeClient(commands, self._settings.kubeconfig)
            raw_clusters = await client.list_bke_clusters()
            if raw_clusters is None:
                errors.append("management_kubeconfig_unreachable")
            else:
                seen: set[str] = set()
                for item in raw_clusters:
                    try:
                        name = await self._sync_cluster(agent_id, client, item, errors)
                        if name:
                            seen.add(name)
                    except Exception as exc:
                        errors.append(f"cluster_sync_failed:{exc}"[:300])
                self._mark_missing_clusters(agent_id, seen)

            await self._sync_apps(agent_id, errors)
            app_issues, console = await self._observe_health_and_console(
                agent_id, errors
            )
            guide_console = await self._probe_guide_console(agent_id)
            return self._snapshot(
                agent_id,
                discovered=True,
                errors=tuple(errors[:8]),
                extra_issues=app_issues,
                console=console,
                guide_console=guide_console,
            )

    async def _sync_cluster(
        self,
        agent_id: str,
        client: KubeClient,
        item: dict[str, Any],
        errors: list[str],
    ) -> str | None:
        metadata = item.get("metadata") or {}
        name = str(metadata.get("name") or "").strip()
        namespace = str(metadata.get("namespace") or name).strip()
        if not name or not namespace:
            return None
        existing = self._repository.get_cluster_by_name(name)
        if existing is not None and existing.agent_id != agent_id:
            errors.append(f"cluster_owned_by_other_agent:{name}")
            return None

        spec = item.get("spec") or {}
        status = item.get("status") or {}
        ready = bool(status.get("ready")) or self._condition_true(
            status.get("conditions"), "Ready"
        )
        endpoint = self._endpoint(spec)
        nodes_raw = await client.list_bke_nodes(namespace, name) or []
        nodes = self._node_specs(nodes_raw)
        environment = self._ready_environment(agent_id)

        if existing is None:
            record = self._repository.create_cluster(
                agent_id=agent_id,
                environment_id=environment.id if environment is not None else None,
                name=name,
                nodes=tuple(nodes),
                status=ClusterStatus.ready if ready else ClusterStatus.creating,
                phase="done" if ready else "wait_ready",
                progress=100 if ready else 50,
            )
        else:
            record = existing
            # 已 ready 的集群被控制台改坏/节点掉线时，也要从 ready 退回来；
            # 正在创建中的集群则以服务端状态机为准，避免和 ClusterRunner 抢写。
            if not (existing.status in CLUSTER_ACTIVE_STATUSES and not ready):
                degraded = not ready and existing.status not in CLUSTER_ACTIVE_STATUSES
                new_status = (
                    ClusterStatus.ready
                    if ready
                    else (ClusterStatus.waiting_ready if degraded else existing.status)
                )
                self._repository.update_cluster(
                    record.id,
                    status=new_status,
                    phase="done"
                    if ready
                    else ("wait_ready" if degraded else existing.phase),
                    progress=100 if ready else (50 if degraded else existing.progress),
                    endpoint=endpoint,
                    expected_node_count=len(nodes) or existing.expected_node_count,
                    error_code=None if ready else existing.error_code,
                    error_message=None if ready else existing.error_message,
                )

        kubeconfig = await self._kubeconfig_path(client, namespace, name, record.id)
        self._repository.update_cluster(
            record.id,
            endpoint=endpoint,
            kubeconfig_path=kubeconfig or record.kubeconfig_path,
        )
        for node in nodes_raw:
            self._sync_node(record.id, node, ready)
        return name

    def _sync_node(
        self, cluster_id: str, item: dict[str, Any], cluster_ready: bool
    ) -> None:
        spec = item.get("spec") or {}
        status = item.get("status") or {}
        ip = str(spec.get("ip") or "").strip()
        if not ip:
            return
        roles = spec.get("role") or []
        role_text = (
            " ".join(str(role) for role in roles)
            if isinstance(roles, list)
            else str(roles)
        )
        role = (
            NodeRole.master
            if "master" in role_text or "etcd" in role_text
            else NodeRole.worker
        )
        state = str(status.get("state") or "").lower()
        if state == "ready":
            node_status = NodeStatus.ready
        elif state in {"failed", "error"}:
            node_status = NodeStatus.failed
        elif cluster_ready:
            node_status = NodeStatus.ready
        else:
            node_status = NodeStatus.bootstrapping
        self._repository.upsert_node(
            cluster_id,
            ip=ip,
            hostname=str(
                spec.get("hostname") or item.get("metadata", {}).get("name") or ip
            ),
            port=int(spec.get("port") or 22),
            username=str(spec.get("username") or "root"),
            role=role.value,
            is_local=ip == self._local_ip,
            status=node_status.value,
            phase="done" if node_status is NodeStatus.ready else "joining",
        )

    async def _sync_apps(self, agent_id: str, errors: list[str]) -> None:
        clusters = [
            item
            for item in self._repository.list_clusters(agent_id=agent_id)
            if item.status == ClusterStatus.ready and item.kubeconfig_path
        ]
        for cluster in clusters:
            if not Path(cluster.kubeconfig_path or "").is_file():
                errors.append(f"kubeconfig_missing:{cluster.name}")
                continue
            commands = CommandRunner(
                cwd=self._work_dir / cluster.id, log=lambda _line: None
            )
            helm = HelmClient(commands, cluster.kubeconfig_path or "")
            try:
                releases = await helm.list_all()
            except HelmError as exc:
                errors.append(f"helm_list_failed:{cluster.name}:{exc}"[:300])
                continue
            seen: set[str] = set()
            for release in releases:
                if release.namespace in _PLATFORM_NAMESPACES:
                    continue
                seen.add(release.name)
                await self._sync_app(agent_id, cluster, release, commands)
            self._mark_missing_apps(agent_id, cluster, seen)

    async def _sync_app(
        self,
        agent_id: str,
        cluster: ClusterRecord,
        release: HelmRelease,
        commands: CommandRunner,
    ) -> None:
        existing = self._repository.get_app_by_release(
            cluster.id, release.namespace, release.name
        )
        status = self._app_status(release)
        node_port, verify_url = await self._service_endpoint(
            commands, cluster, release.namespace, release.name
        )
        if existing is None:
            record = self._repository.create_app(
                cluster_id=cluster.id,
                agent_id=agent_id,
                namespace=release.namespace,
                release_name=release.name,
                repo_name="helm",
                chart_name=release.chart_name,
                chart_version=release.chart_version,
                values_json=None,
                image_override=None,
                status=status,
                phase="deployed" if status == AppStatus.deployed else "installing",
                progress=100 if status == AppStatus.deployed else 50,
            )
            self._repository.update_app(
                record.id,
                node_port=node_port,
                verify_url=verify_url,
                finished_at=datetime.now(UTC) if status == AppStatus.deployed else None,
            )
            return
        if existing.status in APP_ACTIVE_STATUSES:
            return
        self._repository.update_app(
            existing.id,
            status=status,
            phase="deployed" if status == AppStatus.deployed else existing.phase,
            progress=100 if status == AppStatus.deployed else existing.progress,
            chart_name=release.chart_name,
            chart_version=release.chart_version,
            node_port=node_port or existing.node_port,
            verify_url=verify_url or existing.verify_url,
            error_code=None if status == AppStatus.deployed else existing.error_code,
            error_message=None
            if status == AppStatus.deployed
            else existing.error_message,
        )

    async def _service_endpoint(
        self,
        commands: CommandRunner,
        cluster: ClusterRecord,
        namespace: str,
        release: str,
    ) -> tuple[int | None, str | None]:
        client = KubeClient(commands, cluster.kubeconfig_path or "")
        payload = await client.get_json(
            [
                "-n",
                namespace,
                "get",
                "svc",
                "-l",
                f"app.kubernetes.io/instance={release}",
                "-o",
                "json",
            ]
        )
        items = (payload or {}).get("items") or []
        host = _endpoint_host(cluster.endpoint)
        for item in items:
            if not isinstance(item, dict):
                continue
            spec = item.get("spec") or {}
            for port in spec.get("ports") or []:
                if not isinstance(port, dict) or not port.get("nodePort"):
                    continue
                node_port = int(port["nodePort"])
                scheme = "https" if int(port.get("port") or 80) == 443 else "http"
                url = f"{scheme}://{host}:{node_port}/" if host else None
                return node_port, url
        return None, None

    def _mark_missing_apps(
        self, agent_id: str, cluster: ClusterRecord, seen: set[str]
    ) -> None:
        for app in self._repository.list_apps(cluster_id=cluster.id, agent_id=agent_id):
            if app.release_name in seen or app.status in APP_ACTIVE_STATUSES:
                continue
            self._repository.update_app(
                app.id,
                status=AppStatus.failed,
                error_code="APP_NOT_FOUND",
                error_message="Helm release 已不存在，可能已在业务控制台卸载",
                finished_at=datetime.now(UTC),
            )

    def _mark_missing_clusters(self, agent_id: str, seen: set[str]) -> None:
        for cluster in self._repository.list_clusters(agent_id=agent_id):
            if cluster.name in seen or cluster.status in CLUSTER_ACTIVE_STATUSES:
                continue
            self._repository.update_cluster(
                cluster.id,
                status=ClusterStatus.failed,
                error_code="CLUSTER_NOT_FOUND",
                error_message="管理面未找到该 BKECluster，可能已在引导节点控制台删除",
                finished_at=datetime.now(UTC),
            )

    async def _kubeconfig_path(
        self, client: KubeClient, namespace: str, name: str, cluster_id: str
    ) -> str | None:
        existing = self._repository.get_cluster(cluster_id)
        if (
            existing is not None
            and existing.kubeconfig_path
            and Path(existing.kubeconfig_path).is_file()
        ):
            return existing.kubeconfig_path
        content = await client.get_secret_value(namespace, f"{name}-kubeconfig")
        if not content:
            return None
        run_dir = self._work_dir / cluster_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / "kubeconfig"
        path.write_text(content, encoding="utf-8")
        path.chmod(0o600)
        return str(path)

    async def _probe_guide_console(self, agent_id: str) -> ConsoleSessionProbe | None:
        """探测引导节点控制台是否还能保存登录态。

        管理集群被重建后，``30010`` 上可能还挂着上一套 console-service：登录页能开、
        OAuth 回调也返回 200，但会话写不进去（控制台随后会自己删掉 session）。此时
        继续把用户送到该地址只会反复提示“登录已过期”，所以这里主动探测并让前端回落到
        当前可用的平台控制台。
        """
        environment = self._ready_environment(agent_id) or self._latest_environment(
            agent_id
        )
        if environment is None:
            return None
        url = getattr(environment, "console_url", None) or build_console_url(
            getattr(environment, "host", "") or self._local_ip,
            self._settings.console_port,
        )
        if not url:
            return None
        return await probe_console_session(url)

    def _snapshot(
        self,
        agent_id: str,
        *,
        discovered: bool,
        errors: tuple[str, ...],
        extra_issues: list[OverviewIssue] | None = None,
        console: ConsoleEndpoint | None = None,
        guide_console: ConsoleSessionProbe | None = None,
    ) -> ObservedOverview:
        clusters = tuple(self._repository.list_clusters(agent_id=agent_id))
        apps = tuple(self._repository.list_apps(agent_id=agent_id))
        issues = self._build_issues(agent_id, clusters, apps)
        if extra_issues:
            issues.extend(extra_issues)
        return ObservedOverview(
            clusters=clusters,
            apps=apps,
            issues=tuple(issues),
            console=console or ConsoleEndpoint(reason="refresh_async"),
            refreshed_at=datetime.now(UTC).isoformat(),
            errors=errors,
            discovered=discovered,
            guide_console=guide_console,
        )

    def _build_issues(
        self,
        agent_id: str,
        clusters: tuple[ClusterRecord, ...],
        apps: tuple[AppRecord, ...],
    ) -> list[OverviewIssue]:
        issues: list[OverviewIssue] = []
        environment = self._latest_environment(agent_id)
        if environment is None:
            issues.append(
                OverviewIssue(
                    code="ENVIRONMENT_MISSING",
                    severity="info",
                    source="environment",
                    title="还没有引导节点",
                    message="先完成快速入门第 1 步：部署引导节点与控制台。",
                    remediation="在面板点击“部署”完成引导节点初始化。",
                )
            )
        elif environment.status == "failed":
            issues.append(
                OverviewIssue(
                    code="ENVIRONMENT_FAILED",
                    severity="error",
                    source="environment",
                    title="引导节点部署失败",
                    message=environment.error_message
                    or environment.error_code
                    or "未知原因",
                    remediation="查看部署日志；修复预检失败项后重试，不要直接执行 bke reset。",
                    resource_id=environment.id,
                    resource_name=environment.host,
                )
            )
        else:
            preflight = environment.preflight_json or {}
            for check in (preflight.get("checks") or [])[:8]:
                if not isinstance(check, dict) or check.get("status") not in {
                    "warn",
                    "fail",
                }:
                    continue
                issues.append(
                    OverviewIssue(
                        code=f"PREFLIGHT_{check.get('code') or 'CHECK'}",
                        severity="error" if check.get("status") == "fail" else "warn",
                        source="environment",
                        title=str(check.get("title") or "环境预检"),
                        message=str(check.get("message") or ""),
                        remediation="环境预检未通过时不要继续部署；先处理该检查项。",
                        resource_id=environment.id,
                        resource_name=environment.host,
                    )
                )

        if not clusters:
            issues.append(
                OverviewIssue(
                    code="CLUSTER_MISSING",
                    severity="info",
                    source="cluster",
                    title="还没有业务集群",
                    message="业务集群改为在引导节点控制台手动创建，PolyMind 会自动发现。",
                    remediation="打开“引导节点控制台” Tab，在集群管理里创建业务集群。",
                )
            )
        for cluster in clusters:
            if cluster.status != ClusterStatus.ready:
                issues.append(
                    OverviewIssue(
                        code=cluster.error_code or "CLUSTER_NOT_READY",
                        severity="error"
                        if cluster.status == ClusterStatus.failed
                        else "warn",
                        source="cluster",
                        title=f"业务集群 {cluster.name} 未就绪",
                        message=cluster.error_message or f"当前状态：{cluster.status}",
                        remediation="在引导节点控制台检查 BKECluster/BKENode 状态与节点连通性。",
                        resource_id=cluster.id,
                        resource_name=cluster.name,
                    )
                )
                continue
            bad_nodes = [
                node
                for node in self._repository.list_nodes(cluster.id)
                if node.status != NodeStatus.ready
            ]
            if bad_nodes:
                issues.append(
                    OverviewIssue(
                        code="CLUSTER_NODE_NOT_READY",
                        severity="warn",
                        source="node",
                        title=f"集群 {cluster.name} 有节点未就绪",
                        message=", ".join(
                            f"{n.hostname}({n.ip})={n.status}" for n in bad_nodes
                        ),
                        remediation="在控制台查看节点详情；确认 kubelet/网络/磁盘后重试。",
                        resource_id=cluster.id,
                        resource_name=cluster.name,
                    )
                )

        if clusters and not apps:
            issues.append(
                OverviewIssue(
                    code="APP_MISSING",
                    severity="info",
                    source="app",
                    title="业务集群还没有应用",
                    message="可以在业务控制台手动安装，也可以直接在对话里让 PolyMind 安装。",
                    remediation="例如：给集群 <name> 安装 nginx。",
                )
            )
        return issues

    async def _observe_health_and_console(
        self, agent_id: str, errors: list[str]
    ) -> tuple[list[OverviewIssue], ConsoleEndpoint]:
        clusters = [
            item
            for item in self._repository.list_clusters(agent_id=agent_id)
            if item.status == ClusterStatus.ready and item.kubeconfig_path
        ]
        issues: list[OverviewIssue] = []
        for cluster in clusters:
            if not Path(cluster.kubeconfig_path or "").is_file():
                continue
            for app in self._repository.list_apps(
                cluster_id=cluster.id, agent_id=agent_id
            ):
                issues.extend(await self._app_issues(cluster, app, errors))
        if not clusters:
            return issues, ConsoleEndpoint(reason="no_ready_cluster")
        cluster = clusters[0]
        commands = CommandRunner(cwd=self._work_dir, log=lambda _line: None)
        client = KubeClient(commands, cluster.kubeconfig_path or "")
        console = await client.resolve_console_url(
            host=_endpoint_host(cluster.endpoint)
        )
        return issues, console

    async def _app_issues(
        self, cluster: ClusterRecord, app: AppRecord, errors: list[str]
    ) -> list[OverviewIssue]:
        commands = CommandRunner(
            cwd=self._work_dir / cluster.id, log=lambda _line: None
        )
        client = KubeClient(commands, cluster.kubeconfig_path or "")
        selector = f"app.kubernetes.io/instance={app.release_name}"
        payload = await client.get_json(
            [
                "-n",
                app.namespace,
                "get",
                "pods",
                "-l",
                selector,
                "-o",
                "json",
            ]
        )
        items = (payload or {}).get("items") or []
        if not items:
            all_pods = await client.get_json(
                ["-n", app.namespace, "get", "pods", "-o", "json"]
            )
            items = [
                item
                for item in (all_pods or {}).get("items") or []
                if isinstance(item, dict)
                and str((item.get("metadata") or {}).get("name", "")).startswith(
                    app.release_name
                )
            ]
        if payload is None:
            errors.append(f"pod_query_failed:{cluster.name}:{app.release_name}")
            return []
        if not items:
            return [
                OverviewIssue(
                    code="APP_POD_MISSING",
                    severity="warn",
                    source="app",
                    title=f"应用 {app.release_name} 没有运行中的 Pod",
                    message="Helm release 存在，但按 release 标签和名称都没有找到 Pod。",
                    remediation="在业务控制台查看工作负载；确认命名空间与 release 是否正确。",
                    resource_id=app.id,
                    resource_name=app.release_name,
                )
            ]

        reasons: list[str] = []
        details: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str((item.get("metadata") or {}).get("name") or "")
            status = item.get("status") or {}
            for key in ("initContainerStatuses", "containerStatuses"):
                for container in status.get(key) or []:
                    if not isinstance(container, dict):
                        continue
                    waiting = (container.get("state") or {}).get("waiting") or {}
                    reason = str(waiting.get("reason") or "")
                    if reason:
                        reasons.append(reason)
                        message = str(waiting.get("message") or "")
                        details.append(
                            f"{name}/{container.get('name') or '?'}: {reason}"
                            + (f" ({message})" if message else "")
                        )
            phase = str(status.get("phase") or "")
            if phase in {"Pending", "Failed"} and not reasons:
                reasons.append(phase)
                details.append(f"{name}: phase={phase}")
        if not reasons:
            return []
        unique = sorted(set(reasons))
        detail = "; ".join(details)[:800]
        if any(reason in _IMAGE_PULL_REASONS for reason in unique):
            return [
                OverviewIssue(
                    code="APP_IMAGE_PULL_FAILED",
                    severity="error",
                    source="app",
                    title=f"应用 {app.release_name} 镜像拉取失败",
                    message=detail or "Pod 处于 ImagePullBackOff/ErrImagePull。",
                    remediation=(
                        "检查镜像地址是否可达；Bitnami chart 使用非官方镜像时需设置 "
                        "global.security.allowInsecureImages=true；离线环境改为本地 harbor "
                        "镜像并在安装时用 --image 覆盖。"
                    ),
                    resource_id=app.id,
                    resource_name=app.release_name,
                )
            ]
        if any(reason in _CRASH_REASONS for reason in unique):
            return [
                OverviewIssue(
                    code="APP_POD_CRASH_LOOP",
                    severity="error",
                    source="app",
                    title=f"应用 {app.release_name} 容器反复退出",
                    message=detail,
                    remediation="查看 Pod 日志与事件；确认配置/存储/权限后重启或回滚到上一 revision。",
                    resource_id=app.id,
                    resource_name=app.release_name,
                )
            ]
        return [
            OverviewIssue(
                code="APP_POD_NOT_READY",
                severity="warn",
                source="app",
                title=f"应用 {app.release_name} 未完全就绪",
                message=detail,
                remediation="查看 Pod 事件与日志；必要时在对话里让 PolyMind 回滚应用。",
                resource_id=app.id,
                resource_name=app.release_name,
            )
        ]

    def _latest_environment(self, agent_id: str) -> Any | None:
        environments = self._environments.list(agent_id=agent_id)
        return environments[0] if environments else None

    def _ready_environment(self, agent_id: str) -> Any | None:
        for environment in self._environments.list(agent_id=agent_id):
            if environment.status == "ready":
                return environment
        return None

    @staticmethod
    def _app_status(release: HelmRelease) -> str:
        status = release.status.lower()
        if status == "deployed":
            return AppStatus.deployed
        if status == "failed":
            return AppStatus.failed
        return AppStatus.installing

    @staticmethod
    def _condition_true(conditions: Any, kind: str) -> bool:
        for condition in conditions or []:
            if not isinstance(condition, dict):
                continue
            if str(condition.get("type")) != kind:
                continue
            value = condition.get("status")
            if value is True or (isinstance(value, str) and value.lower() == "true"):
                return True
        return False

    @staticmethod
    def _endpoint(spec: dict[str, Any]) -> str | None:
        endpoint = spec.get("controlPlaneEndpoint") or {}
        host = endpoint.get("host")
        port = endpoint.get("port") or 6443
        return f"https://{host}:{port}" if host else None

    def _node_specs(self, items: list[dict[str, Any]]) -> list[NodeSpec]:
        specs: list[NodeSpec] = []
        for item in items:
            spec = item.get("spec") or {}
            ip = str(spec.get("ip") or "").strip()
            if not ip:
                continue
            roles = spec.get("role") or []
            role_text = (
                " ".join(str(role) for role in roles)
                if isinstance(roles, list)
                else str(roles)
            )
            role = (
                NodeRole.master
                if "master" in role_text or "etcd" in role_text
                else NodeRole.worker
            )
            specs.append(
                NodeSpec(
                    ip=ip,
                    hostname=str(spec.get("hostname") or ip),
                    role=role,
                    port=int(spec.get("port") or 22),
                    username=str(spec.get("username") or ""),
                    is_local=ip == self._local_ip,
                )
            )
        return specs


def _endpoint_host(endpoint: str | None) -> str | None:
    if not endpoint:
        return None
    try:
        return urlsplit(endpoint).hostname
    except ValueError:
        return None
