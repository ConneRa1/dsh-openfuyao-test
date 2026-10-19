"""openFuyao Environment 仓储与迁移测试（真实 SQLite 临时库）。"""

from __future__ import annotations

import pytest
from sqlalchemy import inspect

from witty_service.persistence.db import (
    create_session_factory,
    create_sqlite_engine,
    init_db,
)
from witty_service.persistence.openfuyao_repository import (
    HostAlreadyClaimedError,
    OpenFuyaoRepository,
)


@pytest.fixture
def repository(tmp_path) -> OpenFuyaoRepository:
    engine = create_sqlite_engine(f"sqlite:///{tmp_path / 'openfuyao.sqlite3'}")
    init_db(engine, auto_create=True)
    yield OpenFuyaoRepository(create_session_factory(engine))
    engine.dispose()


def test_migration_creates_openfuyao_table(tmp_path) -> None:
    engine = create_sqlite_engine(f"sqlite:///{tmp_path / 'migrate.sqlite3'}")
    try:
        init_db(engine, auto_create=True)
        assert "openfuyao_environments" in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_create_get_and_list(repository: OpenFuyaoRepository) -> None:
    created = repository.create(
        agent_id="agent-1",
        host="192.0.2.10",
        status="preflight",
        phase="preflight",
        progress=0,
        preflight_json={"ready": True},
        os_version="26.09",
    )

    loaded = repository.get(created.id)
    assert loaded is not None
    assert loaded.agent_id == "agent-1"
    assert loaded.host == "192.0.2.10"
    assert loaded.preflight_json == {"ready": True}
    assert repository.get_by_host("192.0.2.10") is not None
    assert [item.id for item in repository.list(agent_id="agent-1")] == [created.id]
    assert repository.list(agent_id="other") == []


def test_duplicate_host_is_rejected(repository: OpenFuyaoRepository) -> None:
    repository.create(
        agent_id="agent-1",
        host="192.0.2.10",
        status="preflight",
        phase="preflight",
        progress=0,
        preflight_json=None,
    )

    with pytest.raises(HostAlreadyClaimedError):
        repository.create(
            agent_id="agent-2",
            host="192.0.2.10",
            status="preflight",
            phase="preflight",
            progress=0,
            preflight_json=None,
        )


def test_update_distinguishes_unset_from_null(repository: OpenFuyaoRepository) -> None:
    created = repository.create(
        agent_id="agent-1",
        host="192.0.2.10",
        status="preflight",
        phase="preflight",
        progress=0,
        preflight_json=None,
        console_url="https://192.0.2.10:30010",
    )

    untouched = repository.update(created.id, progress=10)
    assert untouched is not None
    assert untouched.console_url == "https://192.0.2.10:30010"

    cleared = repository.update(created.id, console_url=None)
    assert cleared is not None
    assert cleared.console_url is None
    assert cleared.progress == 10


def test_try_start_bootstrap_is_atomic_and_status_gated(
    repository: OpenFuyaoRepository,
) -> None:
    created = repository.create(
        agent_id="agent-1",
        host="192.0.2.10",
        status="failed",
        phase="bke_init",
        progress=55,
        preflight_json=None,
        error_code="BKE_INIT_FAILED",
    )

    assert (
        repository.try_start_bootstrap(
            created.id, allowed_statuses=frozenset({"failed"})
        )
        is True
    )
    # 第二次并发请求必须失败，不能重复启动
    assert (
        repository.try_start_bootstrap(
            created.id, allowed_statuses=frozenset({"failed"})
        )
        is False
    )
    running = repository.get(created.id)
    assert running is not None
    assert running.status == "bootstrapping"
    assert running.phase == "preflight"
    assert running.error_code is None
    assert running.started_at is not None


def test_recover_interrupted_marks_only_active_environments(
    repository: OpenFuyaoRepository,
) -> None:
    running = repository.create(
        agent_id="agent-1",
        host="192.0.2.10",
        status="bootstrapping",
        phase="bke_init",
        progress=55,
        preflight_json=None,
    )
    ready = repository.create(
        agent_id="agent-2",
        host="192.0.2.11",
        status="ready",
        phase="done",
        progress=100,
        preflight_json=None,
    )

    assert repository.recover_interrupted() == 1

    recovered = repository.get(running.id)
    assert recovered is not None
    assert recovered.status == "failed"
    assert recovered.error_code == "BOOTSTRAP_INTERRUPTED"
    untouched = repository.get(ready.id)
    assert untouched is not None
    assert untouched.status == "ready"
