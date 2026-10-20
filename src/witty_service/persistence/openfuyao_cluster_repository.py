"""阶段 2/3 仓储：集群、集群节点、应用三张表。

与 ``openfuyao_repository`` 保持同一套写法：``UNSET`` 哨兵区分“不改”与“置空”，
状态推进用条件 UPDATE（``conditional_acquire`` 同款 SQL 形状），中断恢复统一在
``recover_interrupted``。

**密码不入库**：节点表只有 IP/hostname/角色；密码在渲染时从主机侧 nodes.cred 读。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from witty_service.application.openfuyao.cluster_spec import NodeSpec
from witty_service.domain.openfuyao import (
    APP_ACTIVE_STATUSES,
    CLUSTER_ACTIVE_STATUSES,
    AppStatus,
    ClusterStatus,
    ErrorCode,
    NodeStatus,
)
from witty_service.persistence.orm import (
    OpenFuyaoAppORM,
    OpenFuyaoClusterNodeORM,
    OpenFuyaoClusterORM,
)
from witty_service.persistence.resource_state import (
    UNSET,
    Unset,
    conditional_acquire,
    mark_interrupted,
    utcnow,
)

__all__ = [
    "AppRecord",
    "ClusterConflictError",
    "ClusterNodeRecord",
    "ClusterRecord",
    "OpenFuyaoClusterRepository",
]


class ClusterConflictError(Exception):
    """同名集群已存在，或节点集冲突（数据库唯一约束兜底）。"""


@dataclass(slots=True)
class ClusterRecord:
    id: str
    agent_id: str
    environment_id: str | None
    name: str
    namespace: str
    status: str
    phase: str
    progress: int
    expected_node_count: int
    kubeconfig_path: str | None
    endpoint: str | None
    preflight_json: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


@dataclass(slots=True)
class ClusterNodeRecord:
    id: str
    cluster_id: str
    ip: str
    hostname: str
    port: int
    username: str
    role: str
    is_local: bool
    status: str
    phase: str
    error_code: str | None
    last_message: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class AppRecord:
    id: str
    cluster_id: str
    agent_id: str
    namespace: str
    release_name: str
    repo_name: str | None
    chart_name: str | None
    chart_version: str | None
    values_json: dict[str, Any] | None
    image_override: str | None
    status: str
    phase: str
    progress: int
    node_port: int | None
    verify_url: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class OpenFuyaoClusterRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    # ------------------------------------------------------------------
    # 集群：读
    # ------------------------------------------------------------------

    def get_cluster(self, cluster_id: str) -> ClusterRecord | None:
        with self._session_factory() as session:
            row = session.get(OpenFuyaoClusterORM, cluster_id)
            return _cluster(row) if row is not None else None

    def get_cluster_by_name(self, name: str) -> ClusterRecord | None:
        with self._session_factory() as session:
            row = session.scalar(
                select(OpenFuyaoClusterORM).where(OpenFuyaoClusterORM.name == name)
            )
            return _cluster(row) if row is not None else None

    def list_clusters(
        self, *, agent_id: str | None = None
    ) -> list[ClusterRecord]:
        statement = select(OpenFuyaoClusterORM).order_by(
            OpenFuyaoClusterORM.created_at.desc()
        )
        if agent_id is not None:
            statement = statement.where(OpenFuyaoClusterORM.agent_id == agent_id)
        with self._session_factory() as session:
            return [_cluster(row) for row in session.scalars(statement)]

    def list_nodes(self, cluster_id: str) -> list[ClusterNodeRecord]:
        statement = (
            select(OpenFuyaoClusterNodeORM)
            .where(OpenFuyaoClusterNodeORM.cluster_id == cluster_id)
            .order_by(
                OpenFuyaoClusterNodeORM.role.desc(),
                OpenFuyaoClusterNodeORM.ip,
            )
        )
        with self._session_factory() as session:
            return [_node(row) for row in session.scalars(statement)]

    # ------------------------------------------------------------------
    # 集群：写
    # ------------------------------------------------------------------

    def create_cluster(
        self,
        *,
        agent_id: str,
        environment_id: str | None,
        name: str,
        nodes: Sequence[NodeSpec],
        status: str = ClusterStatus.pending,
        phase: str = "pending",
        progress: int = 0,
    ) -> ClusterRecord:
        now = utcnow()
        cluster_id = str(uuid4())
        row = OpenFuyaoClusterORM(
            id=cluster_id,
            agent_id=agent_id,
            environment_id=environment_id,
            name=name,
            namespace=name,
            status=status,
            phase=phase,
            progress=progress,
            expected_node_count=len(nodes),
            created_at=now,
            updated_at=now,
        )
        node_rows = [
            OpenFuyaoClusterNodeORM(
                id=str(uuid4()),
                cluster_id=cluster_id,
                ip=spec.ip,
                hostname=spec.hostname,
                port=spec.port,
                username=spec.username or "root",
                role=spec.role.value,
                is_local=spec.is_local,
                status=NodeStatus.pending,
                phase="pending",
                created_at=now,
                updated_at=now,
            )
            for spec in nodes
        ]
        try:
            with self._session_factory() as session:
                session.add(row)
                # 没有 ORM relationship 时 SQLAlchemy 不知道父子顺序，先 flush 父行
                session.flush()
                session.add_all(node_rows)
                session.commit()
                session.refresh(row)
                return _cluster(row)
        except IntegrityError as exc:
            raise ClusterConflictError(name) from exc

    def update_cluster(
        self,
        cluster_id: str,
        *,
        status: str | Unset | None = UNSET,
        phase: str | Unset | None = UNSET,
        progress: int | Unset | None = UNSET,
        kubeconfig_path: str | Unset | None = UNSET,
        endpoint: str | Unset | None = UNSET,
        preflight_json: dict[str, Any] | Unset | None = UNSET,
        error_code: str | Unset | None = UNSET,
        error_message: str | Unset | None = UNSET,
        started_at: datetime | Unset | None = UNSET,
        finished_at: datetime | Unset | None = UNSET,
    ) -> ClusterRecord | None:
        values: dict[str, Any] = {"updated_at": utcnow()}
        candidates: dict[str, Any] = {
            "status": status,
            "phase": phase,
            "progress": progress,
            "kubeconfig_path": kubeconfig_path,
            "endpoint": endpoint,
            "preflight_json": preflight_json,
            "error_code": error_code,
            "error_message": error_message,
            "started_at": started_at,
            "finished_at": finished_at,
        }
        for key, value in candidates.items():
            if value is not UNSET:
                values[key] = value
        with self._session_factory() as session:
            row = session.get(OpenFuyaoClusterORM, cluster_id)
            if row is None:
                return None
            for key, value in values.items():
                setattr(row, key, value)
            session.commit()
            session.refresh(row)
            return _cluster(row)

    def try_start_cluster(
        self, cluster_id: str, *, allowed_statuses: frozenset[str]
    ) -> bool:
        now = utcnow()
        with self._session_factory() as session:
            return conditional_acquire(
                session,
                model=OpenFuyaoClusterORM,
                record_id=cluster_id,
                allowed_statuses=allowed_statuses,
                values={
                    "status": ClusterStatus.preflight,
                    "phase": "preflight",
                    "progress": 5,
                    "error_code": None,
                    "error_message": None,
                    "started_at": now,
                    "finished_at": None,
                    "updated_at": now,
                },
            )

    def update_node(
        self,
        cluster_id: str,
        ip: str,
        *,
        status: str | Unset | None = UNSET,
        phase: str | Unset | None = UNSET,
        error_code: str | Unset | None = UNSET,
        last_message: str | Unset | None = UNSET,
    ) -> None:
        values: dict[str, Any] = {"updated_at": utcnow()}
        candidates: dict[str, Any] = {
            "status": status,
            "phase": phase,
            "error_code": error_code,
            "last_message": last_message,
        }
        for key, value in candidates.items():
            if value is not UNSET:
                values[key] = value
        with self._session_factory() as session:
            session.execute(
                update(OpenFuyaoClusterNodeORM)
                .where(
                    OpenFuyaoClusterNodeORM.cluster_id == cluster_id,
                    OpenFuyaoClusterNodeORM.ip == ip,
                )
                .values(**values)
            )
            session.commit()

    def set_all_nodes_status(
        self,
        cluster_id: str,
        *,
        status: str,
        phase: str,
        error_code: str | None = None,
        last_message: str | None = None,
    ) -> None:
        with self._session_factory() as session:
            session.execute(
                update(OpenFuyaoClusterNodeORM)
                .where(OpenFuyaoClusterNodeORM.cluster_id == cluster_id)
                .values(
                    status=status,
                    phase=phase,
                    error_code=error_code,
                    last_message=last_message,
                    updated_at=utcnow(),
                )
            )
            session.commit()

    def delete_cluster(self, cluster_id: str) -> None:
        with self._session_factory() as session:
            row = session.get(OpenFuyaoClusterORM, cluster_id)
            if row is not None:
                session.delete(row)
                session.commit()

    def recover_interrupted(self) -> int:
        now = utcnow()
        with self._session_factory() as session:
            count = mark_interrupted(
                session,
                model=OpenFuyaoClusterORM,
                active_statuses=CLUSTER_ACTIVE_STATUSES,
                values={
                    "status": ClusterStatus.failed,
                    "error_code": ErrorCode.CLUSTER_INTERRUPTED,
                    "error_message": "服务重启导致集群创建中断，可重新创建",
                    "finished_at": now,
                    "updated_at": now,
                },
            )
        with self._session_factory() as session:
            session.execute(
                update(OpenFuyaoClusterNodeORM)
                .where(
                    OpenFuyaoClusterNodeORM.status.in_(
                        {
                            NodeStatus.bootstrapping,
                            NodeStatus.joined,
                        }
                    )
                )
                .values(status=NodeStatus.failed, updated_at=now)
            )
            session.commit()
        return count

    # ------------------------------------------------------------------
    # 应用
    # ------------------------------------------------------------------

    def create_app(
        self,
        *,
        cluster_id: str,
        agent_id: str,
        namespace: str,
        release_name: str,
        repo_name: str | None,
        chart_name: str | None,
        chart_version: str | None,
        values_json: dict[str, Any] | None,
        image_override: str | None,
        status: str = AppStatus.pending,
        phase: str = "pending",
        progress: int = 0,
    ) -> AppRecord:
        now = utcnow()
        row = OpenFuyaoAppORM(
            id=str(uuid4()),
            cluster_id=cluster_id,
            agent_id=agent_id,
            namespace=namespace,
            release_name=release_name,
            repo_name=repo_name,
            chart_name=chart_name,
            chart_version=chart_version,
            values_json=values_json,
            image_override=image_override,
            status=status,
            phase=phase,
            progress=progress,
            created_at=now,
            updated_at=now,
        )
        try:
            with self._session_factory() as session:
                session.add(row)
                session.commit()
                session.refresh(row)
                return _app(row)
        except IntegrityError as exc:
            raise ClusterConflictError(release_name) from exc

    def update_app(
        self,
        app_id: str,
        *,
        status: str | Unset | None = UNSET,
        phase: str | Unset | None = UNSET,
        progress: int | Unset | None = UNSET,
        node_port: int | Unset | None = UNSET,
        verify_url: str | Unset | None = UNSET,
        error_code: str | Unset | None = UNSET,
        error_message: str | Unset | None = UNSET,
        started_at: datetime | Unset | None = UNSET,
        finished_at: datetime | Unset | None = UNSET,
    ) -> AppRecord | None:
        values: dict[str, Any] = {"updated_at": utcnow()}
        candidates: dict[str, Any] = {
            "status": status,
            "phase": phase,
            "progress": progress,
            "node_port": node_port,
            "verify_url": verify_url,
            "error_code": error_code,
            "error_message": error_message,
            "started_at": started_at,
            "finished_at": finished_at,
        }
        for key, value in candidates.items():
            if value is not UNSET:
                values[key] = value
        with self._session_factory() as session:
            row = session.get(OpenFuyaoAppORM, app_id)
            if row is None:
                return None
            for key, value in values.items():
                setattr(row, key, value)
            session.commit()
            session.refresh(row)
            return _app(row)

    def get_app(self, app_id: str) -> AppRecord | None:
        with self._session_factory() as session:
            row = session.get(OpenFuyaoAppORM, app_id)
            return _app(row) if row is not None else None

    def get_app_by_release(
        self, cluster_id: str, namespace: str, release_name: str
    ) -> AppRecord | None:
        with self._session_factory() as session:
            row = session.scalar(
                select(OpenFuyaoAppORM).where(
                    OpenFuyaoAppORM.cluster_id == cluster_id,
                    OpenFuyaoAppORM.namespace == namespace,
                    OpenFuyaoAppORM.release_name == release_name,
                )
            )
            return _app(row) if row is not None else None

    def list_apps(
        self, *, cluster_id: str | None = None, agent_id: str | None = None
    ) -> list[AppRecord]:
        statement = select(OpenFuyaoAppORM).order_by(OpenFuyaoAppORM.created_at.desc())
        if cluster_id is not None:
            statement = statement.where(OpenFuyaoAppORM.cluster_id == cluster_id)
        if agent_id is not None:
            statement = statement.where(OpenFuyaoAppORM.agent_id == agent_id)
        with self._session_factory() as session:
            return [_app(row) for row in session.scalars(statement)]

    def recover_interrupted_apps(self) -> int:
        now = utcnow()
        with self._session_factory() as session:
            return mark_interrupted(
                session,
                model=OpenFuyaoAppORM,
                active_statuses=APP_ACTIVE_STATUSES,
                values={
                    "status": AppStatus.failed,
                    "error_code": ErrorCode.APP_INTERRUPTED,
                    "error_message": "服务重启导致应用安装中断，可重新安装",
                    "finished_at": now,
                    "updated_at": now,
                },
            )


def _cluster(row: OpenFuyaoClusterORM) -> ClusterRecord:
    return ClusterRecord(
        id=row.id,
        agent_id=row.agent_id,
        environment_id=row.environment_id,
        name=row.name,
        namespace=row.namespace,
        status=row.status,
        phase=row.phase,
        progress=row.progress,
        expected_node_count=row.expected_node_count,
        kubeconfig_path=row.kubeconfig_path,
        endpoint=row.endpoint,
        preflight_json=row.preflight_json,
        error_code=row.error_code,
        error_message=row.error_message,
        created_at=row.created_at,
        updated_at=row.updated_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


def _node(row: OpenFuyaoClusterNodeORM) -> ClusterNodeRecord:
    return ClusterNodeRecord(
        id=row.id,
        cluster_id=row.cluster_id,
        ip=row.ip,
        hostname=row.hostname,
        port=row.port,
        username=row.username,
        role=row.role,
        is_local=row.is_local,
        status=row.status,
        phase=row.phase,
        error_code=row.error_code,
        last_message=row.last_message,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _app(row: OpenFuyaoAppORM) -> AppRecord:
    return AppRecord(
        id=row.id,
        cluster_id=row.cluster_id,
        agent_id=row.agent_id,
        namespace=row.namespace,
        release_name=row.release_name,
        repo_name=row.repo_name,
        chart_name=row.chart_name,
        chart_version=row.chart_version,
        values_json=row.values_json,
        image_override=row.image_override,
        status=row.status,
        phase=row.phase,
        progress=row.progress,
        node_port=row.node_port,
        verify_url=row.verify_url,
        error_code=row.error_code,
        error_message=row.error_message,
        created_at=row.created_at,
        updated_at=row.updated_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )
