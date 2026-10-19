"""``RuntimeBase._on_openfuyao_event`` 的 openFuyao 控制台信号单测。

openFuyao 部署完成后，agent 用 ``write`` 工具写出约定信号文件；基类据标准
``tool.call.*`` 事件产出 ``openfuyao.open``，驱动前端右侧面板自动打开。
该单测直接驱动基类默认实现，不依赖任何具体 runtime / SDK。
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from witty_agent_server.runtimes.runtime_base import (
    RuntimeBase,
    RuntimeTurnEvent,
    RuntimeType,
    TurnEventType,
)


class _FakeRuntime(RuntimeBase):
    """最小实现，仅用于驱动基类的 ``_on_openfuyao_event``。"""

    runtime_type: RuntimeType = "opencode"

    def _map_events(self, raw: dict[str, Any]) -> Iterator[RuntimeTurnEvent]:
        del raw
        return iter(())


def _run_hook(runtime: _FakeRuntime, *events: RuntimeTurnEvent) -> list[dict[str, Any]]:
    runtime._turn.openfuyao_payload_by_call_id = {}
    out: list[dict[str, Any]] = []
    for event in events:
        out.extend(runtime._on_openfuyao_event(event))
    return out


def _write_started(
    *,
    path: str,
    content: str,
    call_id: str = "call-1",
    tool_name: str = "write",
) -> RuntimeTurnEvent:
    return {
        "type": TurnEventType.TOOL_CALL_STARTED,
        "payload": {
            "stage": "started",
            "tool_name": tool_name,
            "tool_call_id": call_id,
            "arguments": {"file_path": path, "content": content},
        },
    }


def _write_response(
    *, call_id: str = "call-1", is_error: bool = False
) -> RuntimeTurnEvent:
    return {
        "type": TurnEventType.TOOL_CALL_RESPONSE,
        "payload": {
            "stage": "response",
            "name": "write",
            "tool_call_id": call_id,
            "content": "written",
            "is_error": is_error,
        },
    }


_SIGNAL_PATH = ".openfuyao/openfuyao-console.signal"


def test_signal_write_emits_openfuyao_open_with_url() -> None:
    runtime = _FakeRuntime()
    events = _run_hook(
        runtime,
        _write_started(path=_SIGNAL_PATH, content='{"url": "https://10.0.0.1:30010"}'),
        _write_response(),
    )

    assert [e["type"] for e in events] == ["openfuyao.open"]
    assert events[0]["payload"] == {"url": "https://10.0.0.1:30010"}


def test_signal_without_url_opens_panel_with_empty_payload() -> None:
    runtime = _FakeRuntime()
    events = _run_hook(
        runtime,
        _write_started(path=_SIGNAL_PATH, content="{}"),
        _write_response(),
    )

    assert [e["type"] for e in events] == ["openfuyao.open"]
    assert events[0]["payload"] == {}


def test_invalid_json_content_still_opens_panel() -> None:
    runtime = _FakeRuntime()
    events = _run_hook(
        runtime,
        _write_started(path=_SIGNAL_PATH, content="not-json"),
        _write_response(),
    )

    assert events == [{"type": TurnEventType.OPENFUYAO_OPEN, "payload": {}}]


def test_non_signal_write_emits_nothing() -> None:
    runtime = _FakeRuntime()
    events = _run_hook(
        runtime,
        _write_started(path="output/demo.html", content="<h1>hi</h1>"),
        _write_response(),
    )
    assert events == []


def test_other_tool_emits_nothing() -> None:
    runtime = _FakeRuntime()
    events = _run_hook(
        runtime,
        _write_started(path=_SIGNAL_PATH, content="{}", tool_name="read"),
        _write_response(),
    )
    assert events == []


def test_failed_write_does_not_open_panel() -> None:
    runtime = _FakeRuntime()
    events = _run_hook(
        runtime,
        _write_started(path=_SIGNAL_PATH, content='{"url": "https://x:30010"}'),
        _write_response(is_error=True),
    )
    assert events == []


def test_response_without_started_emits_nothing() -> None:
    runtime = _FakeRuntime()
    events = _run_hook(runtime, _write_response())
    assert events == []
