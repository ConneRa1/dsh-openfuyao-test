"""阶段 3 编排服务：在已就绪的业务集群上安装/升级应用并验证。

状态机：``pending → resolving → installing → verifying → deployed``；失败落
``failed + error_code``。幂等：同一 cluster+namespace+release 已 ``deployed`` 时不重复
安装；进行中则跟随；失败可重试（复用同一行）。

验收口径（与计划 §7 A3 对齐）：helm release 成功、Pod 全 Ready、NodePort/HTTP 可达。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

from witty_service.application.openfuyao.app_runner import (
    AppCancelled,
    AppError,
    AppInstallSpec,
    AppResult,
    AppRunner,
)
from witty_service.application.openfuyao.helm import HelmClient, HelmError
from witty_service.application.openfuyao.kube import KubeClient
from witty_service.application.openfuyao.log_tail import (
    DEFAULT_CHUNK_BYTES,
    LogPage,
    read_log_page,
)
from witty_service.application.openfuyao.process import CommandRunner
from witty_service.config import OpenFuyaoSettings
from witty_service.domain.errors import DomainError
from witty_service.domain.openfuyao import AppStatus, ClusterStatus, ErrorCode
from witty_service.persistence.openfuyao_cluster_repository import (
    AppRecord,
    ClusterRecord,
    OpenFuyaoClusterRepository,
)

logger = logging.getLogger(__name__)

__all__ = ["AppService", "CreateAppResult"]

_APP_PROGRESS = {
    "resolving": 20,
    "installing": 55,
    "verifying": 85,
    "deployed": 100,
}


class RunnerLike(Protocol):
    async def run(self) -> AppResult: ...

    async def cancel(self) -> None: ...


RunnerFactory = Callable[..., RunnerLike]


@dataclass(frozen=True, slots=True)
class CreateAppResult:
    app: AppRecord | None
    created: bool
    needs_confirm: bool = False


@dataclass(frozen=True, slots=True)
class AppPreflightCheck:
    code: str
    status: str
    title: str
    message: str
    remediation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "status": self.status,
            "title": self.title,
            "message": self.message,
            "remediation": self.remediation,
        }


@dataclass(frozen=True, slots=True)
class AppPreflightResult:
    ready: bool
    summary: str
    checks: tuple[AppPreflightCheck, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "summary": self.summary,
            "checks": [item.to_dict() for item in self.checks],
        }


class AppService:
    def __init__(
        self,
        *,
        repository: OpenFuyaoClusterRepository,
        settings: OpenFuyaoSettings,
        workspace_root: Path,
        runner_factory: RunnerFactory = AppRunner,
    ) -> None:
        self._repository = repository
        self._settings = settings
        self._work_dir = (
            Path(settings.work_dir)
            if settings.work_dir
            else (workspace_root / "openfuyao")
        )
        self._runner_factory = runner_factory
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._runners: dict[str, RunnerLike] = {}

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def list_apps(
        self, *, cluster_id: str | None = None, agent_id: str | None = None
    ) -> list[AppRecord]:
        return self._repository.list_apps(cluster_id=cluster_id, agent_id=agent_id)

    def get_app(self, app_id: str) -> AppRecord:
        record = self._repository.get_app(app_id)
        if record is None:
            raise DomainError(
                code=ErrorCode.APP_NOT_FOUND,
                message="应用不存在",
                status_code=404,
                details={"app_id": app_id},
            )
        return record

    def log_path(self, app_id: str) -> Path:
        return self._work_dir / app_id / "app.log"

    def read_logs(
        self,
        app_id: str,
        *,
        cursor: int = 0,
        limit_bytes: int = DEFAULT_CHUNK_BYTES,
    ) -> LogPage:
        self.get_app(app_id)
        return read_log_page(
            self.log_path(app_id), cursor=cursor, limit_bytes=limit_bytes
        )

    # ------------------------------------------------------------------
    # 预检
    # ------------------------------------------------------------------

    async def preflight(
        self,
        *,
        agent_id: str,
        cluster_name: str,
        release_name: str,
        namespace: str,
        chart_dir: str | None,
        repo_url: str | None,
        chart: str | None,
        chart_version: str | None,
        image: str | None,
        node_port: int | None,
    ) -> AppPreflightResult:
        """安装前门禁：集群、kubeconfig、chart 来源、release 冲突、NodePort 占用。"""
        checks: list[AppPreflightCheck] = []
        try:
            cluster = self._ready_cluster(agent_id, cluster_name)
        except DomainError as exc:
            checks.append(
                AppPreflightCheck(
                    code=str(exc.code),
                    status="fail",
                    title="业务集群",
                    message=exc.message,
                    remediation="先在引导节点控制台创建并等待业务集群 Ready。",
                )
            )
            return _preflight_result(checks)
        checks.append(
            AppPreflightCheck(
                code="APP-CLUSTER-READY",
                status="pass",
                title="业务集群",
                message=f"{cluster.name} 已就绪",
            )
        )
        if not cluster.kubeconfig_path or not Path(cluster.kubeconfig_path).is_file():
            checks.append(
                AppPreflightCheck(
                    code="APP-KUBECONFIG",
                    status="fail",
                    title="业务集群 kubeconfig",
                    message=f"kubeconfig 不存在：{cluster.kubeconfig_path or '-'}",
                    remediation="在控制台重新下载 kubeconfig，或等待集群就绪后重试。",
                )
            )
        else:
            checks.append(
                AppPreflightCheck(
                    code="APP-KUBECONFIG",
                    status="pass",
                    title="业务集群 kubeconfig",
                    message=str(cluster.kubeconfig_path),
                )
            )
        try:
            spec = _build_spec(
                release_name=release_name,
                namespace=namespace,
                chart_dir=chart_dir,
                repo_url=repo_url,
                chart=chart,
                chart_version=chart_version,
                values=None,
                image=image,
                node_port=node_port,
                verify_url=None,
            )
        except DomainError as exc:
            checks.append(
                AppPreflightCheck(
                    code=str(exc.code),
                    status="fail",
                    title="Chart 来源",
                    message=exc.message,
                    remediation="提供本机存在的 --chart-dir，或 --chart + --repo-url。",
                )
            )
            return _preflight_result(checks)
        checks.append(
            AppPreflightCheck(
                code="APP-CHART",
                status="pass",
                title="Chart 来源",
                message=spec.chart,
            )
        )
        existing = self._repository.get_app_by_release(
            cluster.id, namespace, release_name
        )
        if existing is not None:
            status = "warn" if existing.status == AppStatus.deployed else "fail"
            checks.append(
                AppPreflightCheck(
                    code="APP-RELEASE-EXISTS",
                    status=status,
                    title="Release 已存在",
                    message=f"{namespace}/{release_name} 当前为 {existing.status}",
                    remediation=(
                        "已 deployed 时 install 会幂等返回，不做升级；需要变更请先回滚/卸载。"
                    ),
                )
            )
        if node_port is not None and cluster.kubeconfig_path:
            conflict = await self._node_port_conflict(
                cluster.kubeconfig_path, node_port, exclude=(namespace, release_name)
            )
            checks.append(
                AppPreflightCheck(
                    code="APP-NODEPORT",
                    status="fail" if conflict else "pass",
                    title="NodePort",
                    message=conflict or f"{node_port} 可用",
                    remediation="换一个 30000-32767 的端口，或先释放占用它的 Service。"
                    if conflict
                    else "",
                )
            )
        return _preflight_result(checks)

    async def _node_port_conflict(
        self, kubeconfig: str, node_port: int, *, exclude: tuple[str, str]
    ) -> str | None:
        commands = CommandRunner(cwd=self._work_dir, log=lambda _line: None)
        client = KubeClient(commands, kubeconfig)
        payload = await client.get_json(["get", "svc", "-A", "-o", "json"])
        for item in (payload or {}).get("items") or []:
            if not isinstance(item, dict):
                continue
            metadata = item.get("metadata") or {}
            namespace = str(metadata.get("namespace") or "")
            name = str(metadata.get("name") or "")
            if (namespace, name) == exclude:
                continue
            for port in (item.get("spec") or {}).get("ports") or []:
                if isinstance(port, dict) and port.get("nodePort") == node_port:
                    return f"已被 {namespace}/{name} 占用"
        return None

    # ------------------------------------------------------------------
    # 安装
    # ------------------------------------------------------------------

    async def install(
        self,
        *,
        agent_id: str,
        cluster_name: str,
        release_name: str,
        namespace: str,
        chart_dir: str | None,
        repo_url: str | None,
        chart: str | None,
        chart_version: str | None,
        values: dict[str, Any] | None,
        image: str | None,
        node_port: int | None,
        verify_url: str | None,
        confirm: bool,
    ) -> CreateAppResult:
        cluster = self._ready_cluster(agent_id, cluster_name)
        spec = _build_spec(
            release_name=release_name,
            namespace=namespace,
            chart_dir=chart_dir,
            repo_url=repo_url,
            chart=chart,
            chart_version=chart_version,
            values=values,
            image=image,
            node_port=node_port,
            verify_url=verify_url or _default_verify_url(cluster, node_port),
        )

        existing = self._repository.get_app_by_release(
            cluster.id, spec.namespace, spec.release_name
        )
        if existing is not None:
            if existing.status == AppStatus.deployed:
                return CreateAppResult(app=existing, created=False)
            if existing.status in {
                AppStatus.resolving,
                AppStatus.installing,
                AppStatus.verifying,
            }:
                return CreateAppResult(app=existing, created=False)
        if not confirm:
            return CreateAppResult(app=existing, created=False, needs_confirm=True)

        if existing is None:
            record = self._repository.create_app(
                cluster_id=cluster.id,
                agent_id=agent_id,
                namespace=spec.namespace,
                release_name=spec.release_name,
                repo_name=repo_url,
                chart_name=spec.chart,
                chart_version=chart_version,
                values_json=values,
                image_override=image,
            )
        else:
            record = self._repository.update_app(
                existing.id,
                status=AppStatus.pending,
                phase="pending",
                progress=0,
                error_code=None,
                error_message=None,
                started_at=None,
                finished_at=None,
            ) or existing
        started = self._repository.update_app(
            record.id,
            status=AppStatus.resolving,
            phase="resolving",
            progress=5,
            started_at=_now(),
            finished_at=None,
            error_code=None,
            error_message=None,
        )
        self._start(record.id, cluster, spec)
        return CreateAppResult(app=started or record, created=True)

    def _start(
        self, app_id: str, cluster: ClusterRecord, spec: AppInstallSpec
    ) -> None:
        if not cluster.kubeconfig_path:
            raise DomainError(
                code=ErrorCode.CLUSTER_NOT_READY,
                message="集群缺少 kubeconfig，无法安装应用",
                status_code=409,
            )
        runner = self._runner_factory(
            app_id=app_id,
            cluster_name=cluster.name,
            kubeconfig_path=cluster.kubeconfig_path,
            spec=spec,
            settings=self._settings,
            work_dir=self._work_dir,
            on_progress=lambda phase, status, _message: self._repository.update_app(
                app_id,
                status=status,
                phase=phase,
                progress=_APP_PROGRESS.get(phase, 0),
            ),
        )
        self._runners[app_id] = runner
        task = asyncio.create_task(self._run(app_id, runner))
        self._tasks[app_id] = task
        task.add_done_callback(lambda _task: self._tasks.pop(app_id, None))

    async def _run(self, app_id: str, runner: RunnerLike) -> None:
        try:
            result = await runner.run()
        except AppCancelled as exc:
            self._repository.update_app(
                app_id,
                status=AppStatus.cancelled,
                phase=exc.phase,
                error_code=exc.code,
                error_message=exc.message,
                finished_at=_now(),
            )
        except AppError as exc:
            logger.warning(
                "openFuyao app failed: id=%s code=%s detail=%s",
                app_id,
                exc.code,
                (exc.detail or "")[-500:],
            )
            self._repository.update_app(
                app_id,
                status=AppStatus.failed,
                phase=exc.phase,
                error_code=exc.code,
                error_message=_truncate(exc.message),
                finished_at=_now(),
            )
        except Exception:
            logger.exception("openFuyao app crashed: id=%s", app_id)
            self._repository.update_app(
                app_id,
                status=AppStatus.failed,
                phase="installing",
                error_code=ErrorCode.APP_INSTALL_FAILED,
                error_message="应用安装内部错误，请查看服务日志",
                finished_at=_now(),
            )
        else:
            self._repository.update_app(
                app_id,
                status=AppStatus.deployed,
                phase="deployed",
                progress=100,
                node_port=result.node_port,
                verify_url=result.verify_url,
                error_code=None,
                error_message=None,
                finished_at=_now(),
            )
        finally:
            self._runners.pop(app_id, None)

    async def cancel(self, app_id: str) -> AppRecord:
        self.get_app(app_id)
        runner = self._runners.get(app_id)
        if runner is not None:
            await runner.cancel()
        task = self._tasks.get(app_id)
        if task is not None:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(asyncio.shield(task), timeout=10)
        current = self._repository.get_app(app_id)
        if current is not None and current.status in {
            AppStatus.deployed,
            AppStatus.failed,
            AppStatus.cancelled,
        }:
            return current
        return self._repository.update_app(
            app_id,
            status=AppStatus.cancelled,
            error_code=ErrorCode.APP_CANCELLED,
            error_message="应用安装已取消",
            finished_at=_now(),
        ) or self.get_app(app_id)

    async def rollback(
        self, app_id: str, *, revision: int | None, confirm: bool
    ) -> AppRecord:
        if not confirm:
            raise DomainError(
                code=ErrorCode.CONFIRM_REQUIRED,
                message="回滚会改变运行中的应用，需要 confirm=true",
                status_code=400,
            )
        app = self.get_app(app_id)
        cluster = self._repository.get_cluster(app.cluster_id)
        if cluster is None or not cluster.kubeconfig_path:
            raise DomainError(
                code=ErrorCode.CLUSTER_NOT_READY,
                message="应用所属集群缺少 kubeconfig，无法回滚",
                status_code=409,
            )
        helm = self._helm(cluster.kubeconfig_path, app.id)
        try:
            history = await helm.history(app.release_name, app.namespace)
        except HelmError as exc:
            raise DomainError(
                code=ErrorCode.APP_ROLLBACK_FAILED,
                message="读取 Helm 历史失败",
                status_code=500,
                details={"output": exc.output[-500:]},
            ) from exc
        revisions = sorted(
            int(item.get("revision") or 0)
            for item in history
            if str(item.get("status") or "") in {"deployed", "superseded"}
        )
        target = revision
        if target is None:
            if len(revisions) < 2:
                raise DomainError(
                    code=ErrorCode.APP_ROLLBACK_FAILED,
                    message="没有可回滚的历史版本",
                    status_code=409,
                    details={"revisions": revisions},
                )
            target = revisions[-2]
        try:
            await helm.rollback(app.release_name, app.namespace, target)
        except HelmError as exc:
            raise DomainError(
                code=ErrorCode.APP_ROLLBACK_FAILED,
                message="Helm 回滚失败",
                status_code=500,
                details={"output": exc.output[-500:]},
            ) from exc
        updated = self._repository.update_app(
            app.id,
            status=AppStatus.deployed,
            phase="deployed",
            progress=100,
            error_code=None,
            error_message=None,
            finished_at=_now(),
        )
        return updated or app

    async def uninstall(self, app_id: str, *, confirm: bool) -> AppRecord:
        if not confirm:
            raise DomainError(
                code=ErrorCode.CONFIRM_REQUIRED,
                message="卸载会删除 Helm release，需要 confirm=true",
                status_code=400,
            )
        app = self.get_app(app_id)
        cluster = self._repository.get_cluster(app.cluster_id)
        if cluster is None or not cluster.kubeconfig_path:
            raise DomainError(
                code=ErrorCode.CLUSTER_NOT_READY,
                message="应用所属集群缺少 kubeconfig，无法卸载",
                status_code=409,
            )
        helm = self._helm(cluster.kubeconfig_path, app.id)
        try:
            await helm.uninstall(app.release_name, app.namespace)
        except HelmError as exc:
            raise DomainError(
                code=ErrorCode.APP_UNINSTALL_FAILED,
                message="Helm 卸载失败",
                status_code=500,
                details={"output": exc.output[-500:]},
            ) from exc
        self._repository.delete_app(app.id)
        return app

    def _helm(self, kubeconfig: str, app_id: str) -> HelmClient:
        commands = CommandRunner(
            cwd=self._work_dir / app_id, log=lambda _line: None
        )
        return HelmClient(commands, kubeconfig)

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def recover_stale(self) -> int:
        return self._repository.recover_interrupted_apps()

    async def close(self) -> None:
        for runner in list(self._runners.values()):
            with contextlib.suppress(Exception):
                await runner.cancel()
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks.clear()
        self._runners.clear()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _ready_cluster(self, agent_id: str, cluster_name: str) -> ClusterRecord:
        cluster = self._repository.get_cluster_by_name(cluster_name)
        if cluster is None or cluster.agent_id != agent_id:
            raise DomainError(
                code=ErrorCode.CLUSTER_NOT_FOUND,
                message=f"业务集群 {cluster_name} 不存在",
                status_code=404,
                details={"name": cluster_name},
            )
        if cluster.status != ClusterStatus.ready:
            raise DomainError(
                code=ErrorCode.CLUSTER_NOT_READY,
                message=f"业务集群 {cluster_name} 尚未就绪（{cluster.status}）",
                status_code=409,
                details={"status": cluster.status},
            )
        return cluster


def _build_spec(
    *,
    release_name: str,
    namespace: str,
    chart_dir: str | None,
    repo_url: str | None,
    chart: str | None,
    chart_version: str | None,
    values: dict[str, Any] | None,
    image: str | None,
    node_port: int | None,
    verify_url: str | None,
) -> AppInstallSpec:
    if chart_dir:
        path = Path(chart_dir).expanduser()
        if not path.is_dir():
            raise DomainError(
                code=ErrorCode.CHART_PULL_FAILED,
                message=f"chart 目录不存在：{path}",
                status_code=400,
            )
        chart_ref = str(path)
    elif chart:
        chart_ref = chart
    else:
        raise DomainError(
            code=ErrorCode.CHART_PULL_FAILED,
            message="需要 --chart-dir 或 --chart（配 --repo-url 可选）",
            status_code=400,
        )
    if node_port is not None and not 30000 <= node_port <= 32767:
        raise DomainError(
            code=ErrorCode.APP_INSTALL_FAILED,
            message=f"NodePort 必须在 30000-32767：{node_port}",
            status_code=400,
        )
    return AppInstallSpec(
        release_name=release_name,
        namespace=namespace,
        chart=chart_ref,
        repo_url=repo_url,
        chart_version=chart_version or None,
        values=values or {},
        image=image,
        node_port=node_port,
        verify_url=verify_url,
    )


def _preflight_result(checks: list[AppPreflightCheck]) -> AppPreflightResult:
    passed = sum(1 for item in checks if item.status == "pass")
    warned = sum(1 for item in checks if item.status == "warn")
    failed = sum(1 for item in checks if item.status == "fail")
    return AppPreflightResult(
        ready=failed == 0,
        summary=f"{passed} 通过 · {warned} 警告 · {failed} 失败",
        checks=tuple(checks),
    )


def _default_verify_url(cluster: ClusterRecord, node_port: int | None) -> str | None:
    if node_port is None or not cluster.endpoint:
        return None
    host = urlsplit(cluster.endpoint).hostname
    if not host:
        return None
    return f"http://{host}:{node_port}/"


def _now() -> datetime:
    return datetime.now(UTC)


def _truncate(message: str, limit: int = 800) -> str:
    return message if len(message) <= limit else message[: limit - 3] + "..."
