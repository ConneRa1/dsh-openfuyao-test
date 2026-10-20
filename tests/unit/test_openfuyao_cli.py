"""openFuyao CLI 单测：只验证命令分支，不启动真实后端。"""

from __future__ import annotations

import json
from typing import Any

from witty_service import openfuyao_cli as cli
from witty_service.application.openfuyao.preflight import Gate

_ENVIRONMENT = {
    "id": "env-1",
    "status": "preflight",
    "phase": "preflight",
    "progress": 5,
    "console_url": "https://192.0.2.10:30010",
    "proxy_url": "http://192.0.2.10:3002/",
    "error_code": None,
    "error_message": None,
}


def _report(*, ready: bool) -> dict[str, Any]:
    return {
        "host": "192.0.2.10",
        "checked_at": "2026-10-19T00:00:00+00:00",
        "ready": ready,
        "summary": {"total": 1, "pass": int(ready), "warn": 0, "fail": int(not ready)},
        "checks": [
            {
                "code": "os",
                "title": "操作系统",
                "status": "pass" if ready else "fail",
                "message": "openEuler 26.09" if ready else "系统不匹配",
                "detail": {},
            }
        ],
    }


class _FakeClient:
    def __init__(self, *, ready: bool = True) -> None:
        self.ready = ready
        self.bootstrapped: list[str] = []
        self.cancelled: list[str] = []
        self.environments = [dict(_ENVIRONMENT)]
        #: 轮询时 ``get`` 返回的状态；默认直接成功，便于验证 --wait 的收尾逻辑
        self.poll_status = "ready"

    def close(self) -> None:
        pass

    def create_environment(self, agent_id: str, *, dry_run: bool) -> dict[str, Any]:
        del agent_id
        return {
            "environment": None if dry_run else dict(self.environments[0]),
            "preflight": _report(ready=self.ready),
            "plan": [{"phase": "preflight", "title": "环境预检", "progress": 5}],
            "created": not dry_run,
        }

    def bootstrap(self, environment_id: str) -> dict[str, Any]:
        self.bootstrapped.append(environment_id)
        return {**_ENVIRONMENT, "status": "bootstrapping", "phase": "install_bke"}

    def cancel(self, environment_id: str) -> dict[str, Any]:
        self.cancelled.append(environment_id)
        return {**_ENVIRONMENT, "status": "cancelled"}

    def list(self, agent_id: str) -> list[dict[str, Any]]:
        del agent_id
        return self.environments

    def get(self, environment_id: str) -> dict[str, Any]:
        del environment_id
        current = dict(self.environments[0])
        current.update(
            status=self.poll_status,
            phase="done" if self.poll_status != "failed" else "bke_init",
            progress=100 if self.poll_status == "ready" else 55,
            proxy_url="http://192.0.2.10:3002/",
            error_code="BKE_INIT_FAILED" if self.poll_status == "failed" else None,
        )
        return current

    def logs(self, environment_id: str, cursor: int) -> dict[str, Any]:
        del environment_id, cursor
        return {"lines": ["line"], "next_cursor": 5, "eof": True}


def _run(monkeypatch, args: list[str], client: _FakeClient) -> int:
    monkeypatch.setattr(cli, "_client", lambda _args: client)
    monkeypatch.setenv("WITTY_AGENT_ID", "agent-1")
    return cli.main(args)


def test_deploy_without_confirm_only_preflights(monkeypatch, capsys) -> None:
    client = _FakeClient()

    code = _run(monkeypatch, ["deploy"], client)

    assert code == 2
    assert client.bootstrapped == []
    assert "加 --confirm" in capsys.readouterr().out


def test_deploy_with_confirm_starts_bootstrap(monkeypatch, capsys) -> None:
    client = _FakeClient()

    code = _run(monkeypatch, ["deploy", "--confirm"], client)

    assert code == 0
    assert client.bootstrapped == ["env-1"]
    assert "Bootstrap 已在后台启动" in capsys.readouterr().out


def test_deploy_stops_when_preflight_fails(monkeypatch, capsys) -> None:
    client = _FakeClient(ready=False)

    code = _run(monkeypatch, ["deploy", "--confirm"], client)

    assert code == 3
    assert client.bootstrapped == []
    assert "未通过" in capsys.readouterr().out


def test_dry_run_does_not_create_environment(monkeypatch, capsys) -> None:
    client = _FakeClient()

    code = _run(monkeypatch, ["deploy", "--dry-run"], client)

    assert code == 0
    assert "未创建环境" in capsys.readouterr().out


def test_status_on_preflight_is_not_an_error(monkeypatch, capsys) -> None:
    client = _FakeClient()

    code = _run(monkeypatch, ["status"], client)

    assert code == 0
    assert "status=preflight" in capsys.readouterr().out


def test_cancel_uses_latest_environment(monkeypatch) -> None:
    client = _FakeClient()

    code = _run(monkeypatch, ["cancel"], client)

    assert code == 0
    assert client.cancelled == ["env-1"]


def test_logs_prints_lines(monkeypatch, capsys) -> None:
    client = _FakeClient()

    code = _run(monkeypatch, ["logs"], client)

    assert code == 0
    assert capsys.readouterr().out.strip() == "line"


def test_missing_agent_id_is_reported(monkeypatch, capsys) -> None:
    client = _FakeClient()
    monkeypatch.setattr(cli, "_client", lambda _args: client)
    monkeypatch.delenv("WITTY_AGENT_ID", raising=False)

    code = cli.main(["deploy"])

    assert code == 1
    assert "AGENT_ID_REQUIRED" in capsys.readouterr().err


def test_deploy_json_emits_single_document_with_needs_confirm(
    monkeypatch, capsys
) -> None:
    """--json 只能有一个 JSON 文档，Agent 不该需要“取最后一段”。"""
    client = _FakeClient()

    code = _run(monkeypatch, ["deploy", "--json"], client)

    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["needs_confirm"] is True
    assert payload["exit_code"] == 2
    assert payload["environment"]["id"] == "env-1"
    assert client.bootstrapped == []


def test_deploy_is_idempotent_when_environment_already_ready(
    monkeypatch, capsys
) -> None:
    client = _FakeClient()
    client.environments = [
        {**_ENVIRONMENT, "status": "ready", "phase": "done", "progress": 100}
    ]

    code = _run(monkeypatch, ["deploy", "--confirm"], client)

    assert code == 0
    assert client.bootstrapped == []
    out = capsys.readouterr().out
    assert "已就绪" in out
    assert "http://192.0.2.10:3002/" in out


def test_deploy_follows_running_bootstrap_without_restarting(
    monkeypatch, capsys
) -> None:
    """重复执行同一条命令时，已在跑就跟随，不能报错也不能再启动一个。"""
    client = _FakeClient()
    client.environments = [
        {**_ENVIRONMENT, "status": "bootstrapping", "phase": "bke_init"}
    ]

    code = _run(monkeypatch, ["deploy", "--confirm"], client)

    assert code == 0
    assert client.bootstrapped == []
    assert "已在执行中" in capsys.readouterr().out


def test_deploy_wait_reports_success_and_proxy(monkeypatch, capsys) -> None:
    client = _FakeClient()

    code = _run(
        monkeypatch,
        ["deploy", "--confirm", "--wait", "--interval", "0"],
        client,
    )

    assert code == 0
    assert "部署完成" in capsys.readouterr().out
    assert client.bootstrapped == ["env-1"]


def test_deploy_wait_returns_terminal_failure(monkeypatch, capsys) -> None:
    client = _FakeClient()
    client.poll_status = "failed"

    code = _run(
        monkeypatch,
        ["deploy", "--confirm", "--wait", "--json", "--interval", "0"],
        client,
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 4
    assert payload["exit_code"] == 4
    assert payload["environment"]["error_code"] == "BKE_INIT_FAILED"


def test_status_reports_failed_environment_as_terminal_failure(
    monkeypatch, capsys
) -> None:
    client = _FakeClient()
    client.environments = [
        {**_ENVIRONMENT, "status": "failed", "error_code": "BKE_INIT_FAILED"}
    ]

    code = _run(monkeypatch, ["status", "--json"], client)

    assert code == 4
    assert json.loads(capsys.readouterr().out)["status"] == "failed"


def test_preflight_exit_code_follows_gate_result(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli, "run_preflight", lambda _gate: cli._report_from_dict(_report(ready=False))
    )

    assert cli.main(["preflight"]) == 3

    monkeypatch.setattr(
        cli, "run_preflight", lambda _gate: cli._report_from_dict(_report(ready=True))
    )

    assert cli.main(["preflight"]) == 0
    assert "通过" in capsys.readouterr().out


def test_preflight_gate_option_is_forwarded(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake(gate: object) -> cli.PreflightReport:
        seen["gate"] = gate
        return cli._report_from_dict(_report(ready=True))

    monkeypatch.setattr(cli, "run_preflight", fake)

    assert cli.main(["preflight", "--gate", "node"]) == 0
    assert seen["gate"] == Gate.node  # type: ignore[comparison-overlap]
