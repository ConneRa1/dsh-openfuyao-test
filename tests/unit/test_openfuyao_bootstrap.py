"""openFuyao 控制台健康检查与 Bootstrap Runner 单测。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
import pytest

from witty_service.application.openfuyao.bootstrap_runner import (
    COMPLETE_MARKER,
    BootstrapCancelled,
    BootstrapError,
    BootstrapRunner,
    CommandResult,
    _not_ready_pods,
    _only_os_matrix_failure,
)
from witty_service.application.openfuyao.console_health import (
    build_console_url,
    build_proxy_url,
    check_console,
    console_login_url,
)
from witty_service.application.openfuyao.preflight import (
    PreflightCheck,
    PreflightReport,
)
from witty_service.config import OpenFuyaoSettings
from witty_service.domain.openfuyao import BootstrapPhase, EnvironmentStatus


def _report(*, ready: bool = True) -> PreflightReport:
    status = "pass" if ready else "fail"
    return PreflightReport(
        host="192.0.2.10",
        checked_at="2026-10-19T00:00:00+00:00",
        checks=(
            PreflightCheck(
                code="os",
                title="操作系统",
                status=status,
                message="openEuler 26.09",
                detail={"version": "26.09"},
            ),
        ),
    )


def test_console_urls() -> None:
    assert console_login_url("https://192.0.2.10:30010/") == (
        "https://192.0.2.10:30010/rest/auth/login"
    )
    assert build_console_url("192.0.2.10", 30010) == "https://192.0.2.10:30010"
    assert build_proxy_url("192.0.2.10", 3002) == "http://192.0.2.10:3002/"


@pytest.mark.asyncio
async def test_console_health_accepts_redirect() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(302))

    health = await check_console("https://192.0.2.10:30010", transport=transport)

    assert health.reachable is True
    assert health.http_status == 302


@pytest.mark.asyncio
async def test_console_health_retries_server_errors() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    health = await check_console(
        "https://192.0.2.10:30010",
        retries=2,
        transport=httpx.MockTransport(handler),
    )

    assert calls == 2
    assert health.reachable is False
    assert health.http_status == 500


@pytest.mark.asyncio
async def test_console_health_does_not_retry_client_errors() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404)

    health = await check_console(
        "https://192.0.2.10:30010",
        retries=3,
        transport=httpx.MockTransport(handler),
    )

    assert calls == 1
    assert health.reachable is False


class _FakeRunner(BootstrapRunner):
    def __init__(self, tmp_path: Path) -> None:
        super().__init__(
            environment_id="env-1",
            host="192.0.2.10",
            settings=OpenFuyaoSettings(),
            work_dir=tmp_path,
            on_progress=self._record_progress,
        )
        self.calls: list[str] = []
        self.phases: list[tuple[BootstrapPhase, EnvironmentStatus]] = []
        self.fail_init = False
        self.preflight_output: str | None = None

    def _record_progress(
        self,
        phase: BootstrapPhase,
        status: EnvironmentStatus,
        _message: str,
    ) -> None:
        self.phases.append((phase, status))

    async def _download_script(self) -> Path:
        self.calls.append("download")
        return self._work_dir / "download.sh"

    async def _run_streaming(
        self,
        argv: list[str],
        *,
        timeout: float,
        phase: BootstrapPhase,
        marker: str | None = None,
    ) -> CommandResult:
        del timeout, phase, marker
        if argv[:2] == ["bash", str(self._work_dir / "download.sh")]:
            self.calls.append("install")
            return CommandResult(0, "installed")
        if argv[:2] == ["bke", "preflight"]:
            self.calls.append("bke_preflight")
            if self.preflight_output is not None:
                return CommandResult(3, self.preflight_output)
            return CommandResult(0, "preflight ok")
        self.calls.append("bke_init")
        if self.fail_init:
            return CommandResult(1, "init failed")
        return CommandResult(0, COMPLETE_MARKER, marker_seen=True)

    async def _run_capture(
        self, argv: list[str], *, timeout: float, phase: BootstrapPhase
    ) -> CommandResult:
        del timeout, phase
        if argv[:2] == ["bke", "version"]:
            self.calls.append("version")
            return CommandResult(0, "bke version 26.9.0")
        self.calls.append("pods")
        return CommandResult(0, "")

    async def _wait_console(self) -> None:
        self.calls.append("wait_console")

    async def _wait_pods(self) -> None:
        self.calls.append("wait_pods")


@pytest.mark.asyncio
async def test_runner_executes_steps_in_order(tmp_path) -> None:
    runner = _FakeRunner(tmp_path)

    result = await runner.run(preflight=_report())

    assert runner.calls == [
        "download",
        "install",
        "version",
        "bke_preflight",
        "bke_init",
        "wait_console",
        "wait_pods",
    ]
    assert [phase for phase, _ in runner.phases] == [
        BootstrapPhase.preflight,
        BootstrapPhase.install_bke,
        BootstrapPhase.bke_init,
        BootstrapPhase.wait_console,
    ]
    assert runner.phases[-1][1] == EnvironmentStatus.waiting_console
    assert result.console_url == "https://192.0.2.10:30010"
    assert result.proxy_url == "http://192.0.2.10:3002/"
    assert result.bke_version == "bke version 26.9.0"
    assert result.os_version == "26.09"
    assert runner.log_path.exists()


@pytest.mark.asyncio
async def test_runner_stops_on_failed_preflight(tmp_path) -> None:
    runner = _FakeRunner(tmp_path)

    with pytest.raises(BootstrapError) as exc_info:
        await runner.run(preflight=_report(ready=False))

    assert exc_info.value.code == "PREFLIGHT_FAILED"
    assert runner.calls == []


@pytest.mark.asyncio
async def test_runner_reports_bke_init_failure(tmp_path) -> None:
    runner = _FakeRunner(tmp_path)
    runner.fail_init = True

    with pytest.raises(BootstrapError) as exc_info:
        await runner.run(preflight=_report())

    assert exc_info.value.code == "BKE_INIT_FAILED"
    assert "bke_init" in runner.calls


@pytest.mark.asyncio
async def test_cancel_kills_the_process_group(tmp_path) -> None:
    runner = BootstrapRunner(
        environment_id="env-1",
        host="192.0.2.10",
        settings=OpenFuyaoSettings(),
        work_dir=tmp_path,
    )
    task = asyncio.create_task(
        runner._run_streaming(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout=30,
            phase=BootstrapPhase.bke_init,
        )
    )
    await asyncio.sleep(0.3)

    await runner.cancel()

    with pytest.raises(BootstrapCancelled):
        await asyncio.wait_for(task, timeout=5)


@pytest.mark.asyncio
async def test_command_timeout_is_reported(tmp_path) -> None:
    runner = BootstrapRunner(
        environment_id="env-1",
        host="192.0.2.10",
        settings=OpenFuyaoSettings(),
        work_dir=tmp_path,
    )

    with pytest.raises(BootstrapError) as exc_info:
        await runner._run_streaming(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            timeout=0.2,
            phase=BootstrapPhase.bke_init,
        )

    assert exc_info.value.code == "COMMAND_TIMEOUT"


def test_not_ready_pods_parsing() -> None:
    output = "\n".join(
        [
            "kube-system coredns-1 1/1 Running 0 1m",
            "openfuyao-system console-1 0/1 Pending 0 1m",
            "job completed-job 0/1 Completed 0 1m",
        ]
    )

    assert _not_ready_pods(output) == ["openfuyao-system/console-1=Pending"]


_OS_MATRIX_TABLE = """\
┌────────┬───────────────┬────────────────────┬─────────────────┐
│  状态  │ 检查项        │ 目标               │ 原因及建议      │
├────────┼───────────────┼────────────────────┼─────────────────┤
│  失败  │ 主机发行版及版 │ 节点：bootstrap    │ 发行版不受支持  │
│  失败  │ 内核兼容性    │ 节点：bootstrap    │ 内核不在矩阵中  │
└────────┴───────────────┴────────────────────┴─────────────────┘
"""


def test_only_os_matrix_failure_matches_known_exception() -> None:
    assert _only_os_matrix_failure(_OS_MATRIX_TABLE) is True
    assert _only_os_matrix_failure("│  失败  │ 端口占用 │") is False
    assert _only_os_matrix_failure("") is False


@pytest.mark.asyncio
async def test_runner_can_continue_on_os_matrix_only_failure(tmp_path) -> None:
    runner = _FakeRunner(tmp_path)
    runner._settings = OpenFuyaoSettings(allow_unsupported_os=True)
    runner.preflight_output = _OS_MATRIX_TABLE

    result = await runner.run(preflight=_report())

    assert "bke_init" in runner.calls
    assert result.console_url == "https://192.0.2.10:30010"


@pytest.mark.asyncio
async def test_runner_blocks_os_matrix_failure_by_default(tmp_path) -> None:
    runner = _FakeRunner(tmp_path)
    runner.preflight_output = _OS_MATRIX_TABLE

    with pytest.raises(BootstrapError) as exc_info:
        await runner.run(preflight=_report())

    assert exc_info.value.code == "BKE_PREFLIGHT_FAILED"
