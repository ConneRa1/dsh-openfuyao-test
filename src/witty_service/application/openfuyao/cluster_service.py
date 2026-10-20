"""阶段 2 编排服务：集群创建/预检/取消/销毁/日志。

与 ``EnvironmentService`` 同构：服务只做状态机、幂等与任务生命周期，执行细节在
``ClusterRunner``。三条状态机约定：

1. **幂等**：同名 + 同节点集 → 直接返回现有记录（退出码 0）；同名 + 不同节点集 →
   ``CONFLICT_EXISTS``；执行中 → 跟随现有进度；
2. **失败归因到节点**：``BKENode``/``kubectl`` 说哪台没起来，就写哪台的
   ``status=failed`` + ``error_code``，集群级只保留摘要；
3. **销毁不等于回退**：只删 ``BKECluster``，返回 ``nodes_dirty`` 明确告知节点上
   kubelet/控制面仍在（实测删 CR 后 6443 仍在监听）。
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import socket
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from witty_service.application.openfuyao.cluster_runner import (
    ClusterCancelled,
    ClusterError,
    ClusterResult,
    ClusterRunner,
    PreflightFailure,
    PreflightOutcome,
)
from witty_service.application.openfuyao.cluster_spec import (
    NodeSpec,
    NodeSpecError,
    normalize_nodes,
)
from witty_service.application.openfuyao.kube import KubeClient
from witty_service.application.openfuyao.log_tail import (
    DEFAULT_CHUNK_BYTES,
    LogPage,
    read_log_page,
)
from witty_service.application.openfuyao.node_credentials import CredentialStore
from witty_service.application.openfuyao.preflight import detect_host_ip
from witty_service.application.openfuyao.process import CommandRunner
from witty_service.config import OpenFuyaoSettings
from witty_service.domain.errors import DomainError
from witty_service.domain.openfuyao import (
    CLUSTER_CANCELLABLE_STATUSES,
    CLUSTER_CREATE_ALLOWED_FROM,
    CLUSTER_PLAN,
    CLUSTER_PROGRESS,
    CLUSTER_TERMINAL_STATUSES,
    ClusterPhase,
    ClusterStatus,
    EnvironmentStatus,
    ErrorCode,
    NodeStatus,
)
from witty_service.persistence.openfuyao_cluster_repository import (
    ClusterNodeRecord,
    ClusterRecord,
    OpenFuyaoClusterRepository,
)
from witty_service.persistence.openfuyao_repository import OpenFuyaoRepository

logger = logging.getLogger(__name__)

__all__ = ["ClusterPreflightResult", "ClusterService", "CreateClusterResult"]

_CLUSTER_NAME = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")


class RunnerLike(Protocol):
    async def run(self) -> ClusterResult: ...

    async def cancel(self) -> None: ...


RunnerFactory = Callable[..., RunnerLike]

ProgressCallback = Callable[[ClusterPhase, ClusterStatus, str], None]
NodeCallback = Callable[[str, str, str | None, str], None]
PreflightCallback = Callable[[dict[str, Any]], None]


@dataclass(frozen=True, slots=True)
class CreateClusterResult:
    cluster: ClusterRecord | None
    nodes: tuple[ClusterNodeRecord, ...]
    plan: tuple[dict[str, str | int], ...]
    created: bool
    needs_confirm: bool = False


@dataclass(frozen=True, slots=True)
class ClusterPreflightResult:
    ready: bool
    summary: str
    payload: dict[str, Any]
    failures: tuple[PreflightFailure, ...]
    tolerated: tuple[PreflightFailure, ...]


def _now() -> datetime:
    return datetime.now(UTC)


def _not_found(cluster_id: str) -> DomainError:
    return DomainError(
        code=ErrorCode.CLUSTER_NOT_FOUND,
        message="业务集群不存在",
        status_code=404,
        details={"cluster_id": cluster_id},
    )


class ClusterService:
    def __init__(
        self,
        *,
        repository: OpenFuyaoClusterRepository,
        environment_repository: OpenFuyaoRepository,
        settings: OpenFuyaoSettings,
        workspace_root: Path,
        runner_factory: RunnerFactory = ClusterRunner,
        credential_store: CredentialStore | None = None,
        local_hostname: str | None = None,
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
        self._runner_factory = runner_factory
        self._credentials = credential_store or CredentialStore(
            settings.nodes_credential_file
        )
        self._local_ip = local_ip or settings.host or detect_host_ip()
        self._local_hostname = local_hostname or socket.gethostname()
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._runners: dict[str, RunnerLike] = {}

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def list_clusters(self, *, agent_id: str | None = None) -> list[ClusterRecord]:
        return self._repository.list_clusters(agent_id=agent_id)

    def get_cluster(
        self, identifier: str, *, agent_id: str | None = None
    ) -> ClusterRecord:
        record = self._repository.get_cluster(identifier) or (
            self._repository.get_cluster_by_name(identifier)
        )
        if record is None or (agent_id is not None and record.agent_id != agent_id):
            raise _not_found(identifier)
        return record

    def nodes(self, cluster_id: str) -> tuple[ClusterNodeRecord, ...]:
        return tuple(self._repository.list_nodes(cluster_id))

    def read_logs(
        self,
        cluster_id: str,
        *,
        cursor: int = 0,
        limit_bytes: int = DEFAULT_CHUNK_BYTES,
    ) -> LogPage:
        self.get_cluster(cluster_id)
        return read_log_page(
            self.log_path(cluster_id), cursor=cursor, limit_bytes=limit_bytes
        )

    def log_path(self, cluster_id: str) -> Path:
        return self._work_dir / cluster_id / "cluster.log"

    # ------------------------------------------------------------------
    # 创建
    # ------------------------------------------------------------------

    def resolve_nodes(
        self, raw_nodes: Sequence[dict[str, Any]] | None
    ) -> tuple[NodeSpec, ...]:
        """L1 校验 + 凭据解析；凭据解析失败直接抛 ``NodeSpecError``。"""
        specs = normalize_nodes(
            raw_nodes,
            local_ip=self._local_ip,
            local_hostname=self._local_hostname,
        )
        credentials = self._credentials.resolve_all(specs)
        return tuple(
            replace(spec, username=credentials[spec.ip].username) for spec in specs
        )

    async def create_cluster(
        self,
        *,
        agent_id: str,
        name: str,
        raw_nodes: Sequence[dict[str, Any]] | None,
        confirm: bool,
        dry_run: bool = False,
    ) -> CreateClusterResult:
        _validate_cluster_name(name)
        try:
            nodes = self.resolve_nodes(raw_nodes)
        except NodeSpecError as exc:
            raise DomainError(
                code=exc.code,
                message=exc.message,
                status_code=400,
                details=exc.to_dict(),
            ) from exc

        environment = self._ready_environment(agent_id)

        existing = self._repository.get_cluster_by_name(name)
        if existing is not None:
            if existing.agent_id != agent_id:
                raise DomainError(
                    code=ErrorCode.CONFLICT_EXISTS,
                    message="同名集群已被其他 Agent 占用",
                    status_code=409,
                    details={"name": name},
                )
            if _same_nodes(self.nodes(existing.id), nodes):
                if (
                    existing.status in CLUSTER_CREATE_ALLOWED_FROM
                    and confirm
                    and not dry_run
                    and self._repository.try_start_cluster(
                        existing.id, allowed_statuses=CLUSTER_CREATE_ALLOWED_FROM
                    )
                ):
                    self._start(existing.id, name, nodes)
                    return CreateClusterResult(
                        cluster=self._repository.get_cluster(existing.id),
                        nodes=self.nodes(existing.id),
                        plan=CLUSTER_PLAN,
                        created=True,
                    )
                return CreateClusterResult(
                    cluster=existing,
                    nodes=self.nodes(existing.id),
                    plan=CLUSTER_PLAN,
                    created=False,
                )
            raise DomainError(
                code=ErrorCode.CONFLICT_EXISTS,
                message="同名集群已存在但节点集不同；请换一个集群名或先销毁",
                status_code=409,
                details={
                    "name": name,
                    "existing_nodes": [
                        {"ip": node.ip, "hostname": node.hostname, "role": node.role}
                        for node in self.nodes(existing.id)
                    ],
                },
            )

        if dry_run:
            return CreateClusterResult(
                cluster=None, nodes=(), plan=CLUSTER_PLAN, created=False
            )
        if not confirm:
            return CreateClusterResult(
                cluster=None,
                nodes=(),
                plan=CLUSTER_PLAN,
                created=False,
                needs_confirm=True,
            )

        record = self._repository.create_cluster(
            agent_id=agent_id,
            environment_id=environment.id if environment is not None else None,
            name=name,
            nodes=nodes,
        )
        if not self._repository.try_start_cluster(
            record.id, allowed_statuses=frozenset({ClusterStatus.pending})
        ):
            current = self._repository.get_cluster(record.id)
            raise DomainError(
                code=ErrorCode.CLUSTER_IN_PROGRESS,
                message="该集群已有创建任务在执行",
                status_code=409,
                details={"status": current.status if current else None},
            )
        self._start(record.id, name, nodes)
        return CreateClusterResult(
            cluster=self._repository.get_cluster(record.id),
            nodes=self.nodes(record.id),
            plan=CLUSTER_PLAN,
            created=True,
        )

    def _start(self, cluster_id: str, name: str, nodes: tuple[NodeSpec, ...]) -> None:
        credentials = self._credentials.resolve_all(nodes)
        runner = self._runner_factory(
            cluster_id=cluster_id,
            name=name,
            nodes=nodes,
            credentials=credentials,
            settings=self._settings,
            work_dir=self._work_dir,
            on_progress=lambda phase, status, message: self._apply_progress(
                cluster_id, phase, status
            ),
            on_preflight=lambda payload: self._repository.update_cluster(
                cluster_id, preflight_json=payload
            ),
            on_node=lambda ip, status, code, message: self._repository.update_node(
                cluster_id,
                ip,
                status=status,
                phase=ClusterPhase.done
                if status == NodeStatus.ready
                else ClusterPhase.joining,
                error_code=code,
                last_message=message,
            ),
        )
        self._runners[cluster_id] = runner
        task = asyncio.create_task(self._run(cluster_id, runner))
        self._tasks[cluster_id] = task
        task.add_done_callback(lambda _task: self._tasks.pop(cluster_id, None))

    async def _run(self, cluster_id: str, runner: RunnerLike) -> None:
        try:
            result = await runner.run()
        except ClusterCancelled as exc:
            self._fail_nodes(cluster_id, exc.code, exc.message)
            self._repository.update_cluster(
                cluster_id,
                status=ClusterStatus.cancelled,
                phase=exc.phase,
                error_code=exc.code,
                error_message=exc.message,
                finished_at=_now(),
            )
        except ClusterError as exc:
            logger.warning(
                "openFuyao cluster failed: id=%s code=%s detail=%s",
                cluster_id,
                exc.code,
                (exc.detail or "")[-500:],
            )
            self._fail_nodes(cluster_id, exc.code, exc.message)
            self._repository.update_cluster(
                cluster_id,
                status=ClusterStatus.failed,
                phase=exc.phase,
                error_code=exc.code,
                error_message=_truncate(exc.message),
                finished_at=_now(),
            )
        except Exception:
            logger.exception("openFuyao cluster crashed: id=%s", cluster_id)
            self._fail_nodes(
                cluster_id,
                ErrorCode.CLUSTER_CREATE_FAILED,
                "集群创建内部错误，请查看服务日志",
            )
            self._repository.update_cluster(
                cluster_id,
                status=ClusterStatus.failed,
                phase=ClusterPhase.submitted,
                error_code=ErrorCode.CLUSTER_CREATE_FAILED,
                error_message="集群创建内部错误，请查看服务日志",
                finished_at=_now(),
            )
        else:
            self._mark_ready(cluster_id, result)
        finally:
            self._runners.pop(cluster_id, None)

    def _mark_ready(self, cluster_id: str, result: ClusterResult) -> None:
        self._repository.update_cluster(
            cluster_id,
            status=ClusterStatus.ready,
            phase=ClusterPhase.done,
            progress=100,
            kubeconfig_path=result.kubeconfig_path,
            endpoint=result.endpoint,
            error_code=None,
            error_message=None,
            finished_at=_now(),
        )
        self._repository.set_all_nodes_status(
            cluster_id, status=NodeStatus.ready, phase="done"
        )

    def _apply_progress(
        self,
        cluster_id: str,
        phase: ClusterPhase,
        status: ClusterStatus,
    ) -> None:
        self._repository.update_cluster(
            cluster_id,
            status=status,
            phase=phase,
            progress=CLUSTER_PROGRESS.get(phase, 0),
        )
        if phase == ClusterPhase.submitted:
            self._repository.set_all_nodes_status(
                cluster_id,
                status=NodeStatus.bootstrapping,
                phase=phase.value,
            )

    def _fail_nodes(self, cluster_id: str, code: ErrorCode, message: str) -> None:
        for node in self._repository.list_nodes(cluster_id):
            if node.status in (NodeStatus.ready, NodeStatus.failed):
                continue
            self._repository.update_node(
                cluster_id,
                node.ip,
                status=NodeStatus.failed,
                error_code=code,
                last_message=_truncate(message),
            )

    # ------------------------------------------------------------------
    # 预检（同步）
    # ------------------------------------------------------------------

    async def preflight(
        self,
        *,
        agent_id: str,
        raw_nodes: Sequence[dict[str, Any]] | None,
        name: str = "bke-preflight",
    ) -> ClusterPreflightResult:
        try:
            _validate_cluster_name(name)
            nodes = self.resolve_nodes(raw_nodes)
        except NodeSpecError as exc:
            raise DomainError(
                code=exc.code,
                message=exc.message,
                status_code=400,
                details=exc.to_dict(),
            ) from exc
        runner = self._runner_factory(
            cluster_id=f"preflight-{agent_id}",
            name=name,
            nodes=nodes,
            credentials=self._credentials.resolve_all(nodes),
            settings=self._settings,
            work_dir=self._work_dir,
        )
        outcome: PreflightOutcome = await runner.preflight_only()
        return ClusterPreflightResult(
            ready=outcome.ready,
            summary=outcome.summary(),
            payload=outcome.payload,
            failures=outcome.failures,
            tolerated=outcome.tolerated,
        )

    # ------------------------------------------------------------------
    # 取消 / 销毁
    # ------------------------------------------------------------------

    async def cancel(self, cluster_id: str) -> ClusterRecord:
        record = self.get_cluster(cluster_id)
        if record.status not in CLUSTER_CANCELLABLE_STATUSES:
            raise DomainError(
                code=ErrorCode.CLUSTER_NOT_CANCELLABLE,
                message="该集群当前不可取消",
                status_code=409,
                details={"status": record.status},
            )
        runner = self._runners.get(record.id)
        if runner is not None:
            await runner.cancel()
        task = self._tasks.get(record.id)
        if task is not None:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(asyncio.shield(task), timeout=10)
        current = self._repository.get_cluster(record.id)
        if current is not None and current.status in CLUSTER_TERMINAL_STATUSES:
            return current
        return self._repository.update_cluster(
            record.id,
            status=ClusterStatus.cancelled,
            error_code=ErrorCode.CANCELLED,
            error_message="集群创建已取消",
            finished_at=_now(),
        ) or self.get_cluster(record.id)

    async def destroy(
        self, cluster_id: str, *, confirm: bool
    ) -> tuple[ClusterRecord, tuple[ClusterNodeRecord, ...]]:
        if not confirm:
            raise DomainError(
                code=ErrorCode.CONFIRM_REQUIRED,
                message="销毁为破坏性操作，需要 confirm=true",
                status_code=400,
            )
        record = self.get_cluster(cluster_id)
        if record.status in {
            ClusterStatus.creating,
            ClusterStatus.joining,
            ClusterStatus.waiting_ready,
            ClusterStatus.preflight,
        }:
            raise DomainError(
                code=ErrorCode.CLUSTER_IN_PROGRESS,
                message="集群正在创建中，请先取消再销毁",
                status_code=409,
            )
        nodes = self.nodes(record.id)
        commands = CommandRunner(
            cwd=self._work_dir / record.id, log=lambda _line: None
        )
        client = KubeClient(commands, self._settings.kubeconfig)
        result = await client.delete_cluster(record.namespace, record.name)
        if result.returncode != 0:
            raise DomainError(
                code=ErrorCode.CLUSTER_CREATE_FAILED,
                message="删除 BKECluster 失败，未清理数据库记录",
                status_code=500,
                details={"output": result.output[-500:]},
            )
        self._repository.delete_cluster(record.id)
        return record, nodes

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def recover_stale(self) -> int:
        return self._repository.recover_interrupted()

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

    def _ready_environment(self, agent_id: str) -> Any | None:
        environments = self._environments.list(agent_id=agent_id)
        for environment in environments:
            if environment.status == EnvironmentStatus.ready:
                return environment
        raise DomainError(
            code=ErrorCode.ENVIRONMENT_NOT_FOUND,
            message="该 Agent 还没有就绪的 openFuyao 环境；先完成 Bootstrap 再建业务集群",
            status_code=409,
            details={"agent_id": agent_id},
        )


def _validate_cluster_name(name: str) -> None:
    if not name or len(name) > 63 or not _CLUSTER_NAME.match(name):
        raise DomainError(
            code=ErrorCode.CONFLICT_EXISTS,
            message=f"集群名 {name!r} 不合法：小写字母/数字/'-'，首尾字母数字，≤63",
            status_code=400,
        )


def _same_nodes(
    existing: Sequence[ClusterNodeRecord], desired: Sequence[NodeSpec]
) -> bool:
    left = sorted((node.ip, node.hostname, node.role) for node in existing)
    right = sorted((node.ip, node.hostname, node.role.value) for node in desired)
    return left == right


def _truncate(message: str, limit: int = 800) -> str:
    return message if len(message) <= limit else message[: limit - 3] + "..."
