"""阶段 2 执行器：预检 → 渲染 → ``bke cluster create`` → CR 轮询 → 节点校验。

进程生命周期（独立会话、进程组回收、超时、日志泵）复用
``process.CommandRunner``；这里只负责“跑什么、怎么解释”。

三条与 BKE 实测行为对齐的关键点（见 ``docs/openfuyao-multinode-spike-findings.md``）：

1. **预检用 JSON**：``bke preflight cluster-create --output json`` 的 ``results[]``
   带 ``ruleID/subject/actual/remediation``，退出码 3 = 预检失败，不需要解析中文表格；
2. **创建退出码不等于结果**：退出非 0 也继续轮询 CR，以 ``BKECluster`` 条件与
   业务集群 Node 列表为准；
3. **不清理远端节点**：删 CR 不会卸载 kubelet/控制面（实测），所以销毁只删 CR，
   并把“节点仍残留”的事实回报给调用方（``nodes_dirty``）。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from witty_service.application.openfuyao.cluster_render import (
    build_bundle,
    cleanup_bundle,
    write_bundle,
)
from witty_service.application.openfuyao.cluster_spec import NodeSpec, node_name
from witty_service.application.openfuyao.kube import KubeClient
from witty_service.application.openfuyao.log_tail import truncate_log
from witty_service.application.openfuyao.node_credentials import NodeCredential
from witty_service.application.openfuyao.process import (
    CommandCancelled,
    CommandError,
    CommandResult,
    CommandRunner,
    CommandTimeout,
)
from witty_service.config import OpenFuyaoSettings
from witty_service.domain.openfuyao import (
    ClusterPhase,
    ClusterStatus,
    ErrorCode,
    NodeRole,
    NodeStatus,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ClusterCancelled",
    "ClusterError",
    "ClusterResult",
    "ClusterRunner",
    "PreflightFailure",
    "PreflightOutcome",
    "failed_results",
    "map_preflight_failure",
]

ProgressCallback = Callable[[ClusterPhase, ClusterStatus, str], None]
PreflightCallback = Callable[[dict[str, Any]], None]
NodeCallback = Callable[[str, str, str | None, str], None]

#: 预检失败项 → 我们的错误码（§11.5）。未列出的统一 ``PREFLIGHT_FAILED``。
_RULE_ERROR_CODES: dict[str, ErrorCode] = {
    "CLUSTER-SSH-TRANSPORT": ErrorCode.NODE_UNREACHABLE,
    "CLUSTER-SSH-AUTH": ErrorCode.NODE_UNREACHABLE,
    "CLUSTER-SSH-PRIVILEGE": ErrorCode.NODE_PRIVILEGE_MISSING,
    "CLUSTER-RES-MEMORY": ErrorCode.MEMORY_INSUFFICIENT,
    "CLUSTER-RES-CPU": ErrorCode.NODE_CPU_INSUFFICIENT,
    "CLUSTER-RES-SYSTEM-DISK": ErrorCode.NODE_DISK_INSUFFICIENT,
    "CLUSTER-PLAT-DISTRO": ErrorCode.PREFLIGHT_FAILED,
    "CLUSTER-PLAT-KERNEL": ErrorCode.PREFLIGHT_FAILED,
    "CLUSTER-TOPO-MASTER": ErrorCode.NODE_ROLE_INVALID,
    "CLUSTER-TOPO-ETCD": ErrorCode.NODE_ROLE_INVALID,
    "CLUSTER-TOPO-MASTER-ODD": ErrorCode.NODE_ROLE_INVALID,
    "CLUSTER-UNIQUE-IP": ErrorCode.NODE_ROLE_INVALID,
    "CLUSTER-UNIQUE-HOSTNAME": ErrorCode.NODE_ROLE_INVALID,
}

#: 26.09/6.6.x 已知矩阵例外：只有这两类失败时允许继续（开关见 settings）。
_TOLERABLE_RULES = frozenset({"CLUSTER-PLAT-DISTRO", "CLUSTER-PLAT-KERNEL"})


class ClusterError(RuntimeError):
    """集群执行失败；``code`` 直接落库并映射 CLI 退出码。"""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        phase: ClusterPhase,
        detail: str | None = None,
        node_ip: str | None = None,
        preflight: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.phase = phase
        self.detail = detail
        self.node_ip = node_ip
        self.preflight = preflight


class ClusterCancelled(ClusterError):
    def __init__(self, *, phase: ClusterPhase) -> None:
        super().__init__(ErrorCode.CANCELLED, "集群创建已取消", phase=phase)


@dataclass(frozen=True, slots=True)
class ClusterResult:
    kubeconfig_path: str
    endpoint: str
    node_ips: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PreflightFailure:
    rule_id: str
    subject: str
    status: str
    node_ip: str | None
    code: ErrorCode
    message: str
    remediation: str
    actual: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "subject": self.subject,
            "status": self.status,
            "node_ip": self.node_ip,
            "code": self.code.value,
            "message": self.message,
            "remediation": self.remediation,
            "actual": self.actual,
        }

    @property
    def summary(self) -> str:
        where = f"节点 {self.node_ip} " if self.node_ip else ""
        text = f"{where}{self.rule_id} {self.message}".strip()
        return f"{text}；建议：{self.remediation}" if self.remediation else text


@dataclass(frozen=True, slots=True)
class PreflightOutcome:
    payload: dict[str, Any]
    failures: tuple[PreflightFailure, ...]
    tolerated: tuple[PreflightFailure, ...]

    @property
    def fatal(self) -> tuple[PreflightFailure, ...]:
        return tuple(item for item in self.failures if item not in self.tolerated)

    @property
    def ready(self) -> bool:
        return not self.fatal

    def summary(self) -> str:
        if not self.failures:
            return "节点预检通过"
        fatal = "；".join(item.summary for item in self.fatal[:3])
        return fatal[:800] or "节点预检未通过"


def failed_results(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """从预检 JSON 取失败项。BKE 的 status 是大写 ``PASS/FAIL``。"""
    return [
        item
        for item in payload.get("results") or []
        if isinstance(item, dict) and str(item.get("status") or "").lower() == "fail"
    ]


def map_preflight_failure(
    result: dict[str, Any],
    *,
    node_by_name: dict[str, str],
) -> PreflightFailure:
    rule_id = str(result.get("ruleID") or "")
    subject = str(result.get("subject") or "")
    actual = result.get("actual") or {}
    evidence = result.get("evidence") or []
    observed = ""
    if isinstance(evidence, list):
        for item in evidence:
            if isinstance(item, dict) and item.get("observed"):
                observed = str(item["observed"])
                break
    message = observed or str(result.get("name") or rule_id)
    if isinstance(actual, dict) and actual.get("value") is not None:
        message = f"{message}（实际 {actual.get('value')}）"
    return PreflightFailure(
        rule_id=rule_id,
        subject=subject,
        status=str(result.get("status") or "fail"),
        node_ip=node_by_name.get(subject),
        code=_RULE_ERROR_CODES.get(rule_id, ErrorCode.PREFLIGHT_FAILED),
        message=message,
        remediation=str(result.get("remediation") or ""),
        actual=actual if isinstance(actual, dict) else {},
    )


class ClusterRunner:
    def __init__(
        self,
        *,
        cluster_id: str,
        name: str,
        nodes: tuple[NodeSpec, ...],
        credentials: dict[str, NodeCredential],
        settings: OpenFuyaoSettings,
        work_dir: Path,
        on_progress: ProgressCallback | None = None,
        on_preflight: PreflightCallback | None = None,
        on_node: NodeCallback | None = None,
    ) -> None:
        self._cluster_id = cluster_id
        self._name = name
        self._nodes = nodes
        self._credentials = credentials
        self._settings = settings
        self._run_dir = work_dir / cluster_id
        self._bundle_dir = self._run_dir / "bundle"
        self._log_path = self._run_dir / "cluster.log"
        self._on_progress = on_progress
        self._on_preflight = on_preflight
        self._on_node = on_node
        self._log_handle: Any = None
        self._commands: CommandRunner | None = None
        self._phase = ClusterPhase.preflight
        self._cancelled = False

    @property
    def log_path(self) -> Path:
        return self._log_path

    # ------------------------------------------------------------------
    # 对外
    # ------------------------------------------------------------------

    async def preflight_only(self) -> PreflightOutcome:
        """同步预检（dry-run/``cluster preflight`` 用），不创建任何资源。"""
        self._run_dir.mkdir(parents=True, exist_ok=True)
        truncate_log(self._log_path)
        self._log_handle = self._log_path.open("a", encoding="utf-8", buffering=1)
        try:
            cluster_path, nodes_path = self._write_bundle()
            outcome = await self._preflight(cluster_path, nodes_path)
            return outcome
        finally:
            cleanup_bundle(self._bundle_dir)
            if self._log_handle is not None:
                self._log_handle.close()
                self._log_handle = None

    async def run(self) -> ClusterResult:
        self._run_dir.mkdir(parents=True, exist_ok=True)
        truncate_log(self._log_path)
        self._log_handle = self._log_path.open("a", encoding="utf-8", buffering=1)
        try:
            self._enter(ClusterPhase.preflight, ClusterStatus.preflight, "节点预检")
            cluster_path, nodes_path = self._write_bundle()
            outcome = await self._preflight(cluster_path, nodes_path)
            if self._on_preflight is not None:
                self._on_preflight(outcome.payload)
            if not outcome.ready:
                self._mark_failed_nodes(outcome.failures)
                raise ClusterError(
                    outcome.fatal[0].code,
                    outcome.summary(),
                    phase=ClusterPhase.preflight,
                    detail="\n".join(item.summary for item in outcome.fatal),
                    preflight=outcome.payload,
                )

            self._enter(ClusterPhase.submitted, ClusterStatus.creating, "提交集群创建")
            await self._create(cluster_path, nodes_path)

            self._enter(
                ClusterPhase.control_plane,
                ClusterStatus.creating,
                "等待控制面就绪",
            )
            await self._wait_control_plane()

            self._enter(ClusterPhase.joining, ClusterStatus.joining, "等待节点加入")
            self._enter(
                ClusterPhase.wait_ready,
                ClusterStatus.waiting_ready,
                "等待节点全部 Ready",
            )
            await self._wait_nodes_ready()
            self._enter(ClusterPhase.done, ClusterStatus.ready, "集群已就绪")
            master = next(
                node for node in self._nodes if node.role is NodeRole.master
            )
            return ClusterResult(
                kubeconfig_path=self._settings.cluster_kubeconfig,
                endpoint=f"https://{master.ip}:6443",
                node_ips=tuple(node.ip for node in self._nodes),
            )
        finally:
            cleanup_bundle(self._bundle_dir)
            if self._log_handle is not None:
                self._log_handle.close()
                self._log_handle = None

    async def cancel(self) -> None:
        self._cancelled = True
        if self._commands is not None:
            await self._commands.cancel()

    # ------------------------------------------------------------------
    # 步骤
    # ------------------------------------------------------------------

    async def _preflight(self, cluster_path: Path, nodes_path: Path) -> PreflightOutcome:
        result = await self._run_capture(
            [
                "bke",
                "preflight",
                "cluster-create",
                "-f",
                str(cluster_path),
                "-n",
                str(nodes_path),
                "--output",
                "json",
                "--kubeconfig",
                self._settings.kubeconfig,
            ],
            timeout=self._settings.cluster_preflight_timeout_seconds,
            phase=ClusterPhase.preflight,
        )
        payload = _parse_preflight_json(result.output)
        if payload is None:
            raise ClusterError(
                ErrorCode.PREFLIGHT_FAILED,
                "bke preflight 未返回可解析的 JSON",
                phase=ClusterPhase.preflight,
                detail=result.output[-2000:],
            )
        node_by_name = self._node_name_map()
        failures = tuple(
            map_preflight_failure(item, node_by_name=node_by_name)
            for item in failed_results(payload)
        )
        tolerated = tuple(
            item
            for item in failures
            if self._settings.allow_unsupported_os and item.rule_id in _TOLERABLE_RULES
        )
        if tolerated:
            self._log(
                "WARN: 仅 OS/内核矩阵不匹配，按 OPENFUYAO_ALLOW_UNSUPPORTED_OS 继续："
                + "；".join(item.summary for item in tolerated)
            )
        return PreflightOutcome(
            payload=payload, failures=failures, tolerated=tolerated
        )

    async def _create(self, cluster_path: Path, nodes_path: Path) -> None:
        result = await self._run_streaming(
            [
                "bke",
                "cluster",
                "create",
                "-f",
                str(cluster_path),
                "-n",
                str(nodes_path),
                "--kubeconfig",
                self._settings.kubeconfig,
            ],
            timeout=self._settings.cluster_create_timeout_seconds,
            phase=ClusterPhase.submitted,
        )
        if result.returncode != 0:
            # 退出码非 0 不判死：BKE 常在最后一步返回非 0，但 CR 仍会继续收敛。
            self._log(
                f"WARN: bke cluster create 退出码 {result.returncode}，转 CR 轮询判定"
            )

    async def _wait_control_plane(self) -> None:
        client = self._management_client()
        deadline = (
            asyncio.get_running_loop().time()
            + self._settings.cluster_ready_timeout_seconds
        )
        last = ""
        while asyncio.get_running_loop().time() < deadline:
            self._require_not_cancelled(ClusterPhase.control_plane)
            observation = await client.observe_cluster(self._name, self._name)
            current = (
                f"found={observation.found} ready={observation.ready} "
                f"healthy={observation.healthy} {observation.message}"
            )
            if current != last:
                self._log(f"bkecluster: {current}")
                last = current
            if observation.found and observation.ready:
                return
            if observation.found and observation.failed_message:
                self._log(f"bkecluster 未就绪：{observation.failed_message}")
            await self._sleep(5)

        nodes = await client.observe_bke_nodes(self._name, self._name)
        for spec in self._nodes:
            name = node_name(
                self._name, spec, _worker_index(self._nodes, spec)
            )
            observation = nodes.get(name)
            if observation is not None and not observation.ready and observation.message:
                self._on_node_failed(spec.ip, ErrorCode.NODE_NOT_READY, observation.message)
        raise ClusterError(
            ErrorCode.CLUSTER_CREATE_TIMEOUT,
            "等待 BKECluster 就绪超时",
            phase=ClusterPhase.control_plane,
            detail=last,
        )

    async def _wait_nodes_ready(self) -> None:
        business = KubeClient(self._command(), self._settings.cluster_kubeconfig)
        expected_names = {
            spec.hostname: spec for spec in self._nodes
        }
        deadline = (
            asyncio.get_running_loop().time()
            + self._settings.cluster_ready_timeout_seconds
        )
        last = ""
        nodes: dict[str, Any] = {}
        while asyncio.get_running_loop().time() < deadline:
            self._require_not_cancelled(ClusterPhase.wait_ready)
            nodes = await business.observe_kube_nodes()
            current = ", ".join(
                f"{name}={'Ready' if item.ready else item.status or 'NotReady'}"
                for name, item in sorted(nodes.items())
            )
            if current != last:
                self._log(f"kube nodes: {current or '（尚不可读）'}")
                last = current
            if len(nodes) >= len(expected_names) and all(
                item.ready for item in nodes.values()
            ):
                missing = set(expected_names) - set(nodes)
                if not missing:
                    for spec in self._nodes:
                        self._on_node(spec.ip, NodeStatus.ready.value, None, "Ready")
                    return
            await self._sleep(5)

        failed = False
        for spec in self._nodes:
            item = nodes.get(spec.hostname)
            if item is None:
                continue
            failed = True
            self._on_node_failed(
                spec.ip, ErrorCode.NODE_NOT_READY, item.message or item.status
            )
        if not failed:
            raise ClusterError(
                ErrorCode.NODE_COUNT_MISMATCH,
                f"业务集群节点数与预期不符：期望 {len(expected_names)}，"
                f"实际 {len(nodes)}",
                phase=ClusterPhase.wait_ready,
                detail=last,
            )
        raise ClusterError(
            ErrorCode.NODE_NOT_READY,
            "存在未 Ready 的节点",
            phase=ClusterPhase.wait_ready,
            detail=last,
        )

    # ------------------------------------------------------------------
    # 渲染 / 日志 / 命令
    # ------------------------------------------------------------------

    def _write_bundle(self) -> tuple[Path, Path]:
        bundle = build_bundle(
            self._name,
            self._nodes,
            passwords={ip: cred.password for ip, cred in self._credentials.items()},
        )
        return write_bundle(self._bundle_dir, bundle)

    def _node_name_map(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for spec in self._nodes:
            mapping[node_name(self._name, spec, _worker_index(self._nodes, spec))] = (
                spec.ip
            )
        return mapping

    def _management_client(self) -> KubeClient:
        return KubeClient(self._command(), self._settings.kubeconfig)

    def _command(self) -> CommandRunner:
        if self._commands is None:
            self._commands = CommandRunner(cwd=self._run_dir, log=self._log)
        return self._commands

    async def _run_capture(
        self, argv: list[str], *, timeout: float, phase: ClusterPhase
    ) -> CommandResult:
        self._phase = phase
        try:
            return await self._command().run_capture(argv, timeout=timeout)
        except CommandCancelled as exc:
            raise ClusterCancelled(phase=phase) from exc
        except CommandTimeout as exc:
            raise ClusterError(
                ErrorCode.COMMAND_TIMEOUT, str(exc), phase=phase, detail=exc.output
            ) from exc
        except CommandError as exc:
            raise ClusterError(
                ErrorCode.COMMAND_NOT_FOUND, str(exc), phase=phase, detail=exc.output
            ) from exc

    async def _run_streaming(
        self, argv: list[str], *, timeout: float, phase: ClusterPhase
    ) -> CommandResult:
        self._phase = phase
        try:
            return await self._command().run_streaming(argv, timeout=timeout)
        except CommandCancelled as exc:
            raise ClusterCancelled(phase=phase) from exc
        except CommandTimeout as exc:
            raise ClusterError(
                ErrorCode.CLUSTER_CREATE_TIMEOUT,
                str(exc),
                phase=phase,
                detail=exc.output,
            ) from exc
        except CommandError as exc:
            raise ClusterError(
                ErrorCode.COMMAND_NOT_FOUND, str(exc), phase=phase, detail=exc.output
            ) from exc

    async def _sleep(self, seconds: float) -> None:
        # 等待期间保持可取消：取消时 CommandRunner.cancel 会打断在途命令，
        # 这里只睡固定间隔，5s 的取消延迟可接受。
        await asyncio.sleep(seconds)

    def _require_not_cancelled(self, phase: ClusterPhase) -> None:
        if self._cancelled:
            raise ClusterCancelled(phase=phase)

    def _enter(
        self, phase: ClusterPhase, status: ClusterStatus, message: str
    ) -> None:
        self._phase = phase
        self._log(f"== {message} ==")
        if self._on_progress is not None:
            self._on_progress(phase, status, message)

    def _on_node_failed(self, ip: str, code: ErrorCode, message: str) -> None:
        if self._on_node is not None:
            self._on_node(ip, NodeStatus.failed.value, code.value, message[:500])

    def _mark_failed_nodes(self, failures: tuple[PreflightFailure, ...]) -> None:
        for failure in failures:
            if failure.node_ip:
                self._on_node_failed(failure.node_ip, failure.code, failure.message)

    def _log(self, message: str) -> None:
        if self._log_handle is not None:
            self._log_handle.write(message + "\n")


def _worker_index(nodes: tuple[NodeSpec, ...], target: NodeSpec) -> int:
    """与 ``render_node_docs`` 一致的 worker 序号（master 固定 1）。"""
    if target.role is NodeRole.master:
        return 1
    index = 0
    for spec in nodes:
        if spec.role is NodeRole.worker:
            index += 1
            if spec.ip == target.ip:
                return index
    return index


def _parse_preflight_json(output: str) -> dict[str, Any] | None:
    """stdout 是单个 JSON；stderr/进度行混入时取最后一个完整 JSON 对象。"""
    text = output.strip()
    if not text:
        return None
    try:
        payload = __import__("json").loads(text)
    except ValueError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            payload = json.loads(text[start : end + 1])
        except ValueError:
            return None
    return payload if isinstance(payload, dict) else None
