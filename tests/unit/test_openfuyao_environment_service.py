"""openFuyao EnvironmentService 单测：状态机、并发、取消与日志游标。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from witty_service.application.openfuyao.bootstrap_runner import (
    BootstrapCancelled,
    BootstrapResult,
)
from witty_service.application.openfuyao.environment_service import EnvironmentService
from witty_service.application.openfuyao.preflight import (
    PreflightCheck,
    PreflightReport,
)
from witty_service.config import OpenFuyaoSettings
from witty_service.domain.errors import DomainError
from witty_service.domain.openfuyao import BootstrapPhase, EnvironmentStatus
from witty_service.persistence.db import (
    create_session_factory,
    create_sqlite_engine,
    init_db,
)
from witty_service.persistence.openfuyao_repository import OpenFuyaoRepository


def _report(*, ready: bool = True) -> PreflightReport:
    return PreflightReport(
        host="192.0.2.10",
        checked_at="2026-10-19T00:00:00+00:00",
        checks=(
            PreflightCheck(
                code="os",
                title="操作系统",
                status="pass" if ready else "fail",
                message="openEuler 26.09" if ready else "系统不匹配",
                detail={"version": "26.09"},
            ),
        ),
    )


class _Agents:
    def get_agent(self, agent_id: str) -> Any | None:
        return object() if agent_id.startswith("agent-") else None


class _FakeRunner:
    def __init__(self, **kwargs: Any) -> None:
        self.environment_id = kwargs["environment_id"]
        self.on_progress = kwargs["on_progress"]
        self.cancelled = False
        self.block = asyncio.Event()
        self.started = asyncio.Event()

    async def run(self, *, preflight: PreflightReport) -> BootstrapResult:
        del preflight
        self.on_progress(
            BootstrapPhase.install_bke,
            EnvironmentStatus.bootstrapping,
            "安装 BKE",
        )
        self.started.set()
        await self.block.wait()
        if self.cancelled:
            raise BootstrapCancelled(phase=BootstrapPhase.bke_init)
        return BootstrapResult(
            console_url="https://192.0.2.10:30010",
            proxy_url="http://192.0.2.10:3002/",
            bke_version="26.9.0",
            os_version="26.09",
        )

    async def cancel(self) -> None:
        self.cancelled = True
        self.block.set()


class _Harness:
    def __init__(self, tmp_path: Path, *, ready: bool = True) -> None:
        engine = create_sqlite_engine(f"sqlite:///{tmp_path / 'svc.sqlite3'}")
        init_db(engine, auto_create=True)
        self.engine = engine
        self.repository = OpenFuyaoRepository(create_session_factory(engine))
        self.runners: list[_FakeRunner] = []
        self.report = _report(ready=ready)

        def factory(**kwargs: Any) -> _FakeRunner:
            runner = _FakeRunner(**kwargs)
            self.runners.append(runner)
            return runner

        self.service = EnvironmentService(
            repository=self.repository,
            agent_repository=_Agents(),
            settings=OpenFuyaoSettings(
                host="192.0.2.10",
                work_dir=str(tmp_path / "work"),
            ),
            workspace_root=tmp_path,
            runner_factory=factory,
            preflight_runner=lambda: self.report,
        )

    async def close(self) -> None:
        await self.service.close()
        self.engine.dispose()


@pytest.mark.asyncio
async def test_create_persists_preflight_and_claims_host(tmp_path) -> None:
    harness = _Harness(tmp_path)
    try:
        result = await harness.service.create_environment(agent_id="agent-1")

        assert result.created is True
        assert result.environment is not None
        assert result.environment.status == "preflight"
        assert result.environment.progress == 5
        assert result.environment.console_url == "https://192.0.2.10:30010"
        assert result.environment.preflight_json is not None
        assert result.plan[0]["phase"] == "preflight"

        with pytest.raises(DomainError) as exc_info:
            await harness.service.create_environment(agent_id="agent-2")
        assert exc_info.value.code == "HOST_ALREADY_CLAIMED"
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_create_unknown_agent_is_rejected(tmp_path) -> None:
    harness = _Harness(tmp_path)
    try:
        with pytest.raises(DomainError) as exc_info:
            await harness.service.create_environment(agent_id="missing")
        assert exc_info.value.code == "AGENT_NOT_FOUND"
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_create_with_failed_preflight_persists_failure(tmp_path) -> None:
    harness = _Harness(tmp_path, ready=False)
    try:
        result = await harness.service.create_environment(agent_id="agent-1")

        assert result.environment is not None
        assert result.environment.status == "failed"
        assert result.environment.error_code == "PREFLIGHT_FAILED"
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_bootstrap_requires_confirm(tmp_path) -> None:
    harness = _Harness(tmp_path)
    try:
        created = await harness.service.create_environment(agent_id="agent-1")
        assert created.environment is not None
        with pytest.raises(DomainError) as exc_info:
            await harness.service.bootstrap(created.environment.id, confirm=False)
        assert exc_info.value.code == "CONFIRM_REQUIRED"
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_bootstrap_success_reaches_ready(tmp_path) -> None:
    harness = _Harness(tmp_path)
    try:
        created = await harness.service.create_environment(agent_id="agent-1")
        assert created.environment is not None
        started = await harness.service.bootstrap(created.environment.id, confirm=True)
        assert started.status == "bootstrapping"

        task = harness.service._tasks[created.environment.id]
        harness.runners[0].block.set()
        await asyncio.wait_for(task, timeout=2)

        ready = harness.service.get_environment(created.environment.id)
        assert ready.status == "ready"
        assert ready.phase == "done"
        assert ready.progress == 100
        assert ready.console_url == "https://192.0.2.10:30010"
        assert ready.bke_version == "26.9.0"
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_concurrent_bootstrap_is_rejected_and_cancel_works(tmp_path) -> None:
    harness = _Harness(tmp_path)
    try:
        created = await harness.service.create_environment(agent_id="agent-1")
        assert created.environment is not None
        await harness.service.bootstrap(created.environment.id, confirm=True)
        await asyncio.wait_for(harness.runners[0].started.wait(), timeout=2)

        with pytest.raises(DomainError) as exc_info:
            await harness.service.bootstrap(created.environment.id, confirm=True)
        assert exc_info.value.code == "BOOTSTRAP_IN_PROGRESS"

        cancelled = await harness.service.cancel(created.environment.id)
        assert cancelled.status == "cancelled"
        assert harness.runners[0].cancelled is True
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_bootstrap_with_failed_preflight_marks_failed(tmp_path) -> None:
    harness = _Harness(tmp_path, ready=True)
    try:
        created = await harness.service.create_environment(agent_id="agent-1")
        assert created.environment is not None
        harness.report = _report(ready=False)

        with pytest.raises(DomainError) as exc_info:
            await harness.service.bootstrap(created.environment.id, confirm=True)
        assert exc_info.value.code == "PREFLIGHT_FAILED"
        failed = harness.service.get_environment(created.environment.id)
        assert failed.status == "failed"
        assert failed.error_code == "PREFLIGHT_FAILED"
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_health_uses_console_url(tmp_path, monkeypatch) -> None:
    harness = _Harness(tmp_path)
    try:
        created = await harness.service.create_environment(agent_id="agent-1")
        assert created.environment is not None
        seen: list[str] = []

        async def fake_check(url: str) -> Any:
            seen.append(url)
            return type(
                "Health",
                (),
                {"to_dict": lambda self: {"console_reachable": False}},
            )()

        monkeypatch.setattr(
            "witty_service.application.openfuyao.environment_service.check_console",
            fake_check,
        )
        health = await harness.service.health(created.environment.id)
        assert seen == ["https://192.0.2.10:30010"]
        assert health.to_dict() == {"console_reachable": False}
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_log_cursor_returns_complete_lines_only(tmp_path) -> None:
    harness = _Harness(tmp_path)
    try:
        created = await harness.service.create_environment(agent_id="agent-1")
        assert created.environment is not None
        log_path = (
            Path(harness.service._work_dir) / created.environment.id / "bootstrap.log"
        )
        log_path.parent.mkdir(parents=True)
        log_path.write_text("line-1\nline-2\npartial", encoding="utf-8")

        first = harness.service.read_logs(created.environment.id)
        assert first.lines == ["line-1", "line-2"]
        assert first.eof is False

        with log_path.open("a", encoding="utf-8") as handle:
            handle.write("-done\n")
        second = harness.service.read_logs(
            created.environment.id, cursor=first.next_cursor
        )
        assert second.lines == ["partial-done"]
        assert second.eof is True
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_recover_stale_marks_interrupted(tmp_path) -> None:
    harness = _Harness(tmp_path, ready=False)
    try:
        created = await harness.service.create_environment(agent_id="agent-1")
        assert created.environment is not None
        harness.repository.update(
            created.environment.id, status="bootstrapping", phase="bke_init"
        )

        assert harness.service.recover_stale() == 1
        recovered = harness.service.get_environment(created.environment.id)
        assert recovered.status == "failed"
        assert recovered.error_code == "BOOTSTRAP_INTERRUPTED"
    finally:
        await harness.close()
