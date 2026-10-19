"""openFuyao CLI 单测：只验证命令分支，不启动真实后端。"""

from __future__ import annotations

from typing import Any

from witty_service import openfuyao_cli as cli

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

    def close(self) -> None:
        pass

    def create_environment(self, agent_id: str, *, dry_run: bool) -> dict[str, Any]:
        del agent_id
        return {
            "environment": None if dry_run else dict(_ENVIRONMENT),
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
        return self.environments[0]

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

    assert code == 0
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

    assert code == 2
    assert client.bootstrapped == []
    assert "未通过" in capsys.readouterr().out


def test_dry_run_does_not_create_environment(monkeypatch, capsys) -> None:
    client = _FakeClient()

    code = _run(monkeypatch, ["deploy", "--dry-run"], client)

    assert code == 0
    assert "未创建环境" in capsys.readouterr().out


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
