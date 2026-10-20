"""通用持久化操作单测：更新哨兵、条件占位、中断恢复。

用 openFuyao 资源表当被测模型——它就是这套操作的第一个使用者，
阶段 2/3 的 cluster/app 仓储只需要传自己的 ORM 与状态集合。
"""

from __future__ import annotations

from datetime import UTC

import pytest
from sqlalchemy import select

from witty_service.persistence.db import (
    create_session_factory,
    create_sqlite_engine,
    init_db,
)
from witty_service.persistence.orm import OpenFuyaoEnvironmentORM
from witty_service.persistence.resource_state import (
    UNSET,
    Unset,
    conditional_acquire,
    mark_interrupted,
    utcnow,
)


@pytest.fixture
def session_factory(tmp_path):
    engine = create_sqlite_engine(f"sqlite:///{tmp_path / 'state.sqlite3'}")
    init_db(engine, auto_create=True)
    yield create_session_factory(engine)
    engine.dispose()


def _row(session_factory, *, host: str, status: str) -> str:
    now = utcnow()
    with session_factory() as session:
        row = OpenFuyaoEnvironmentORM(
            id=f"env-{host}",
            agent_id="agent-1",
            host=host,
            status=status,
            phase="preflight",
            progress=0,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.commit()
    return row.id


def _status(session_factory, environment_id: str) -> str:
    with session_factory() as session:
        row = session.get(OpenFuyaoEnvironmentORM, environment_id)
        assert row is not None
        return row.status


def test_unset_is_a_singleton_sentinel() -> None:
    assert repr(UNSET) == "UNSET"
    assert isinstance(UNSET, Unset)
    assert Unset() is not UNSET


def test_utcnow_is_timezone_aware() -> None:
    assert utcnow().tzinfo is UTC


def test_conditional_acquire_is_atomic_and_status_gated(session_factory) -> None:
    environment_id = _row(session_factory, host="192.0.2.10", status="failed")
    values = {"status": "bootstrapping", "progress": 5, "updated_at": utcnow()}

    with session_factory() as session:
        assert (
            conditional_acquire(
                session,
                model=OpenFuyaoEnvironmentORM,
                record_id=environment_id,
                allowed_statuses=frozenset({"failed"}),
                values=values,
            )
            is True
        )
    with session_factory() as session:
        # 第二次：状态已经推进，不能被重复占位
        assert (
            conditional_acquire(
                session,
                model=OpenFuyaoEnvironmentORM,
                record_id=environment_id,
                allowed_statuses=frozenset({"failed"}),
                values=values,
            )
            is False
        )

    assert _status(session_factory, environment_id) == "bootstrapping"


def test_conditional_acquire_ignores_other_rows(session_factory) -> None:
    target = _row(session_factory, host="192.0.2.10", status="ready")
    other = _row(session_factory, host="192.0.2.11", status="ready")

    with session_factory() as session:
        assert (
            conditional_acquire(
                session,
                model=OpenFuyaoEnvironmentORM,
                record_id=target,
                allowed_statuses=frozenset({"failed"}),
                values={"status": "bootstrapping"},
            )
            is False
        )

    assert _status(session_factory, target) == "ready"
    assert _status(session_factory, other) == "ready"


def test_mark_interrupted_only_touches_active_statuses(session_factory) -> None:
    running = _row(session_factory, host="192.0.2.10", status="bootstrapping")
    waiting = _row(session_factory, host="192.0.2.11", status="waiting_console")
    ready = _row(session_factory, host="192.0.2.12", status="ready")

    now = utcnow()
    with session_factory() as session:
        affected = mark_interrupted(
            session,
            model=OpenFuyaoEnvironmentORM,
            active_statuses=frozenset({"bootstrapping", "waiting_console"}),
            values={
                "status": "failed",
                "error_code": "BOOTSTRAP_INTERRUPTED",
                "error_message": "服务重启导致 Bootstrap 中断，可重新部署",
                "finished_at": now,
                "updated_at": now,
            },
        )

    assert affected == 2
    assert _status(session_factory, running) == "failed"
    assert _status(session_factory, waiting) == "failed"
    assert _status(session_factory, ready) == "ready"

    with session_factory() as session:
        recovered = session.scalar(
            select(OpenFuyaoEnvironmentORM).where(OpenFuyaoEnvironmentORM.id == running)
        )
        assert recovered is not None
        assert recovered.error_code == "BOOTSTRAP_INTERRUPTED"
        assert recovered.finished_at is not None


def test_mark_interrupted_returns_zero_when_nothing_active(session_factory) -> None:
    _row(session_factory, host="192.0.2.10", status="ready")

    with session_factory() as session:
        assert (
            mark_interrupted(
                session,
                model=OpenFuyaoEnvironmentORM,
                active_statuses=frozenset({"bootstrapping"}),
                values={"status": "failed"},
            )
            == 0
        )
