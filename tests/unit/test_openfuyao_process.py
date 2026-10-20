"""受控子进程执行器单测：提权前缀、超时、取消、日志与输出保留。"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from witty_service.application.openfuyao.process import (
    CommandCancelled,
    CommandNotAvailable,
    CommandRunner,
    CommandTimeout,
    privileged,
)


def _runner(tmp_path: Path, *, log: list[str] | None = None) -> CommandRunner:
    collected: list[str] = log if log is not None else []

    def _log(message: str) -> None:
        collected.append(message)

    return CommandRunner(cwd=tmp_path / "work", log=_log)


def test_root_runs_command_directly(monkeypatch) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: 0)

    assert privileged(["bke", "version"]) == ["bke", "version"]


def test_non_root_uses_non_interactive_sudo(monkeypatch) -> None:
    """``-n`` 是安全前提：拿不到免密就立刻失败，不能卡在密码提示上。"""
    monkeypatch.setattr(os, "geteuid", lambda: 1001)

    assert privileged(["bke", "version"]) == ["sudo", "-n", "bke", "version"]


@pytest.mark.asyncio
async def test_capture_returns_stdout_and_logs_command(tmp_path) -> None:
    log: list[str] = []
    runner = _runner(tmp_path, log=log)

    result = await runner.run_capture(
        [sys.executable, "-c", "print('hello')"], timeout=10
    )

    assert result.returncode == 0
    assert result.output == "hello"
    assert log[0].startswith("$ ")
    assert "hello" in log


@pytest.mark.asyncio
async def test_streaming_sees_marker(tmp_path) -> None:
    runner = _runner(tmp_path)
    script = "print('BKE initialization is complete')"

    result = await runner.run_streaming(
        [sys.executable, "-c", script], timeout=10, marker="is complete"
    )

    assert result.returncode == 0
    assert result.marker_seen is True


@pytest.mark.asyncio
async def test_timeout_keeps_output_tail(tmp_path) -> None:
    runner = _runner(tmp_path)
    script = "import time; print('partial output', flush=True); time.sleep(5)"

    with pytest.raises(CommandTimeout) as exc_info:
        await runner.run_streaming([sys.executable, "-c", script], timeout=0.3)

    assert exc_info.value.code == "COMMAND_TIMEOUT"
    assert "partial output" in exc_info.value.output
    assert "0.3" in str(exc_info.value)


@pytest.mark.asyncio
async def test_missing_binary_is_reported(tmp_path) -> None:
    runner = _runner(tmp_path)

    with pytest.raises(CommandNotAvailable) as exc_info:
        await runner.run_capture(["definitely-not-a-binary-xyz"], timeout=5)

    assert exc_info.value.code == "COMMAND_NOT_FOUND"
    assert "definitely-not-a-binary-xyz" in str(exc_info.value)


@pytest.mark.asyncio
async def test_cancel_interrupts_streaming_and_marks_runner_cancelled(
    tmp_path,
) -> None:
    runner = _runner(tmp_path)
    task = asyncio.create_task(
        runner.run_streaming(
            [sys.executable, "-c", "import time; time.sleep(30)"], timeout=30
        )
    )
    await asyncio.sleep(0.3)

    await runner.cancel()

    assert runner.cancelled is True
    with pytest.raises(CommandCancelled):
        await asyncio.wait_for(task, timeout=5)


@pytest.mark.asyncio
async def test_cancelled_runner_refuses_new_commands(tmp_path) -> None:
    runner = _runner(tmp_path)
    await runner.cancel()

    with pytest.raises(CommandCancelled):
        await runner.run_capture([sys.executable, "-c", "pass"], timeout=5)


@pytest.mark.asyncio
async def test_cwd_is_created_for_direct_calls(tmp_path) -> None:
    """Runner 直接调用（单测/阶段 2 复用）时也要能自己建工作目录。"""
    runner = _runner(tmp_path)

    await runner.run_capture([sys.executable, "-c", "pass"], timeout=5)

    assert (tmp_path / "work").is_dir()
