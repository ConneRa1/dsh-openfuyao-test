"""openFuyao Environment 仓储：单表 CRUD 与并发占位。

与 `channel_repository` 一样独立成模块，避免继续膨胀 `SqliteRepository`。
这里只做持久化，状态机与进程编排在 `application/openfuyao/` 内。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from witty_service.persistence.orm import OpenFuyaoEnvironmentORM

ACTIVE_STATUSES: Final = ("bootstrapping", "waiting_console")


class HostAlreadyClaimedError(Exception):
    """同一 host 已被其他 Environment 占用（数据库唯一约束兜底）。"""


class _Unset:
    __slots__ = ()

    def __repr__(self) -> str:
        return "UNSET"


UNSET = _Unset()


def utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class OpenFuyaoEnvironmentRecord:
    id: str
    agent_id: str
    host: str
    status: str
    phase: str
    progress: int
    console_url: str | None
    proxy_url: str | None
    bke_version: str | None
    os_version: str | None
    preflight_json: dict[str, Any] | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class OpenFuyaoRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    # ------------------------------------------------------------------
    # 读
    # ------------------------------------------------------------------

    def get(self, environment_id: str) -> OpenFuyaoEnvironmentRecord | None:
        with self._session_factory() as session:
            row = session.get(OpenFuyaoEnvironmentORM, environment_id)
            return self._to_record(row) if row is not None else None

    def get_by_host(self, host: str) -> OpenFuyaoEnvironmentRecord | None:
        with self._session_factory() as session:
            row = session.scalar(
                select(OpenFuyaoEnvironmentORM).where(
                    OpenFuyaoEnvironmentORM.host == host
                )
            )
            return self._to_record(row) if row is not None else None

    def list(self, *, agent_id: str | None = None) -> list[OpenFuyaoEnvironmentRecord]:
        statement = select(OpenFuyaoEnvironmentORM).order_by(
            OpenFuyaoEnvironmentORM.created_at.desc()
        )
        if agent_id is not None:
            statement = statement.where(OpenFuyaoEnvironmentORM.agent_id == agent_id)
        with self._session_factory() as session:
            return [self._to_record(row) for row in session.scalars(statement)]

    # ------------------------------------------------------------------
    # 写
    # ------------------------------------------------------------------

    def create(
        self,
        *,
        agent_id: str,
        host: str,
        preflight_json: dict[str, Any] | None,
        status: str,
        phase: str,
        progress: int,
        console_url: str | None = None,
        proxy_url: str | None = None,
        os_version: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> OpenFuyaoEnvironmentRecord:
        now = utcnow()
        row = OpenFuyaoEnvironmentORM(
            id=str(uuid4()),
            agent_id=agent_id,
            host=host,
            status=status,
            phase=phase,
            progress=progress,
            console_url=console_url,
            proxy_url=proxy_url,
            os_version=os_version,
            preflight_json=preflight_json,
            error_code=error_code,
            error_message=error_message,
            created_at=now,
            updated_at=now,
        )
        try:
            with self._session_factory() as session:
                session.add(row)
                session.commit()
                session.refresh(row)
                return self._to_record(row)
        except IntegrityError as exc:
            raise HostAlreadyClaimedError(host) from exc

    def update(
        self,
        environment_id: str,
        *,
        status: str | _Unset | None = UNSET,
        phase: str | _Unset | None = UNSET,
        progress: int | _Unset | None = UNSET,
        console_url: str | _Unset | None = UNSET,
        proxy_url: str | _Unset | None = UNSET,
        bke_version: str | _Unset | None = UNSET,
        os_version: str | _Unset | None = UNSET,
        preflight_json: dict[str, Any] | _Unset | None = UNSET,
        error_code: str | _Unset | None = UNSET,
        error_message: str | _Unset | None = UNSET,
        started_at: datetime | _Unset | None = UNSET,
        finished_at: datetime | _Unset | None = UNSET,
    ) -> OpenFuyaoEnvironmentRecord | None:
        values: dict[str, Any] = {"updated_at": utcnow()}
        candidates = {
            "status": status,
            "phase": phase,
            "progress": progress,
            "console_url": console_url,
            "proxy_url": proxy_url,
            "bke_version": bke_version,
            "os_version": os_version,
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
            row = session.get(OpenFuyaoEnvironmentORM, environment_id)
            if row is None:
                return None
            for key, value in values.items():
                setattr(row, key, value)
            session.commit()
            session.refresh(row)
            return self._to_record(row)

    def try_start_bootstrap(
        self, environment_id: str, *, allowed_statuses: frozenset[str]
    ) -> bool:
        """原子地把环境推进到 bootstrapping；已在进行中或被禁止时返回 False。"""
        now = utcnow()
        with self._session_factory() as session:
            result = session.execute(
                update(OpenFuyaoEnvironmentORM)
                .where(
                    OpenFuyaoEnvironmentORM.id == environment_id,
                    OpenFuyaoEnvironmentORM.status.in_(allowed_statuses),
                )
                .values(
                    status="bootstrapping",
                    phase="preflight",
                    progress=5,
                    error_code=None,
                    error_message=None,
                    started_at=now,
                    finished_at=None,
                    updated_at=now,
                )
            )
            session.commit()
            return bool(result.rowcount)

    def recover_interrupted(self) -> int:
        """服务重启后把进行中的环境标记失败，避免前端永远转圈。"""
        now = utcnow()
        with self._session_factory() as session:
            result = session.execute(
                update(OpenFuyaoEnvironmentORM)
                .where(OpenFuyaoEnvironmentORM.status.in_(ACTIVE_STATUSES))
                .values(
                    status="failed",
                    error_code="BOOTSTRAP_INTERRUPTED",
                    error_message="服务重启导致 Bootstrap 中断，可重新部署",
                    finished_at=now,
                    updated_at=now,
                )
            )
            session.commit()
            return int(result.rowcount or 0)

    @staticmethod
    def _to_record(row: OpenFuyaoEnvironmentORM) -> OpenFuyaoEnvironmentRecord:
        return OpenFuyaoEnvironmentRecord(
            id=row.id,
            agent_id=row.agent_id,
            host=row.host,
            status=row.status,
            phase=row.phase,
            progress=row.progress,
            console_url=row.console_url,
            proxy_url=row.proxy_url,
            bke_version=row.bke_version,
            os_version=row.os_version,
            preflight_json=row.preflight_json,
            error_code=row.error_code,
            error_message=row.error_message,
            created_at=row.created_at,
            updated_at=row.updated_at,
            started_at=row.started_at,
            finished_at=row.finished_at,
        )
