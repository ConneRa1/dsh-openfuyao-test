"""openFuyao API 端点测试：鉴权、创建/查询、冲突与日志。"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

import witty_service.config as _config
from witty_service import main as main_module
from witty_service.api.services import ServiceContainer
from witty_service.application.openfuyao.preflight import (
    PreflightCheck,
    PreflightReport,
)
from witty_service.persistence.db import create_session_factory, create_sqlite_engine
from witty_service.persistence.orm import Base
from witty_service.persistence.repositories import SqliteRepository
from witty_service.storage.workspace_store import LocalWorkspaceStore

AUTH = {"Authorization": "Bearer test-token"}


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


def _build(tmp_path, monkeypatch) -> tuple[TestClient, ServiceContainer]:
    monkeypatch.setenv("AUTH_TOKEN", "test-token")
    monkeypatch.setenv("OPENFUYAO_HOST", "192.0.2.10")
    monkeypatch.setattr(_config, "_settings", None)
    engine = create_sqlite_engine(f"sqlite:///{tmp_path / 'openfuyao-api.sqlite3'}")
    Base.metadata.create_all(engine)
    repository = SqliteRepository(create_session_factory(engine))
    repository.create_agent(
        name="deployer",
        sandbox_type="local_process",
        adapter_type="opencode",
        workspace_path=str(tmp_path / "workspace" / "deployer"),
        idle_timeout_seconds=60,
    )
    services = ServiceContainer(
        repository=repository,
        workspace_store=LocalWorkspaceStore(base_path=tmp_path / "workspace"),
    )
    services.get_openfuyao_service()._preflight_runner = lambda: _report()
    client = TestClient(main_module.create_app(services=services))
    return client, services


def _agent_id(services: ServiceContainer) -> str:
    return services.repository.list_agents()[0].id


def test_openfuyao_endpoints_require_auth(tmp_path, monkeypatch) -> None:
    client, _ = _build(tmp_path, monkeypatch)

    assert client.get("/openfuyao/environments").status_code == 401
    assert (
        client.get(
            "/openfuyao/environments", headers={"Authorization": "Bearer nope"}
        ).status_code
        == 401
    )


def test_create_list_and_get_environment(tmp_path, monkeypatch) -> None:
    client, services = _build(tmp_path, monkeypatch)
    agent_id = _agent_id(services)

    response = client.post(
        "/openfuyao/environments", json={"agent_id": agent_id}, headers=AUTH
    )

    assert response.status_code == 201
    body = response.json()
    assert body["created"] is True
    assert body["environment"]["status"] == "preflight"
    assert body["environment"]["agent_id"] == agent_id
    assert body["environment"]["proxy_url"] == "http://192.0.2.10:3002/"
    assert body["preflight"]["ready"] is True
    assert [step["phase"] for step in body["plan"]] == [
        "preflight",
        "install_bke",
        "bke_init",
        "wait_console",
    ]
    environment_id = body["environment"]["id"]

    listed = client.get(f"/openfuyao/environments?agent_id={agent_id}", headers=AUTH)
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [environment_id]

    fetched = client.get(f"/openfuyao/environments/{environment_id}", headers=AUTH)
    assert fetched.status_code == 200
    assert fetched.json()["id"] == environment_id


def test_dry_run_returns_plan_without_persisting(tmp_path, monkeypatch) -> None:
    client, services = _build(tmp_path, monkeypatch)

    response = client.post(
        "/openfuyao/environments",
        json={"agent_id": _agent_id(services), "dry_run": True},
        headers=AUTH,
    )

    assert response.status_code == 200
    assert response.json()["created"] is False
    assert response.json()["environment"] is None
    assert services.get_openfuyao_service().list_environments() == []


def test_second_agent_cannot_claim_same_host(tmp_path, monkeypatch) -> None:
    client, services = _build(tmp_path, monkeypatch)
    first_agent = _agent_id(services)
    second = services.repository.create_agent(
        name="other",
        sandbox_type="local_process",
        adapter_type="opencode",
        workspace_path=str(tmp_path / "workspace" / "other"),
        idle_timeout_seconds=60,
    )

    assert (
        client.post(
            "/openfuyao/environments", json={"agent_id": first_agent}, headers=AUTH
        ).status_code
        == 201
    )
    conflict = client.post(
        "/openfuyao/environments", json={"agent_id": second.id}, headers=AUTH
    )

    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "HOST_ALREADY_CLAIMED"


def test_bootstrap_requires_confirm(tmp_path, monkeypatch) -> None:
    client, services = _build(tmp_path, monkeypatch)
    created = client.post(
        "/openfuyao/environments",
        json={"agent_id": _agent_id(services)},
        headers=AUTH,
    )
    environment_id = created.json()["environment"]["id"]

    response = client.post(
        f"/openfuyao/environments/{environment_id}/bootstrap",
        json={"confirm": False},
        headers=AUTH,
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CONFIRM_REQUIRED"


def test_logs_endpoint_is_empty_before_bootstrap(tmp_path, monkeypatch) -> None:
    client, services = _build(tmp_path, monkeypatch)
    created = client.post(
        "/openfuyao/environments",
        json={"agent_id": _agent_id(services)},
        headers=AUTH,
    )
    environment_id = created.json()["environment"]["id"]

    response = client.get(
        f"/openfuyao/environments/{environment_id}/logs", headers=AUTH
    )

    assert response.status_code == 200
    assert response.json() == {
        "cursor": 0,
        "next_cursor": 0,
        "lines": [],
        "eof": True,
    }


def test_health_endpoint_uses_service_probe(tmp_path, monkeypatch) -> None:
    client, services = _build(tmp_path, monkeypatch)
    created = client.post(
        "/openfuyao/environments",
        json={"agent_id": _agent_id(services)},
        headers=AUTH,
    )
    environment_id = created.json()["environment"]["id"]

    class _Health:
        def to_dict(self) -> dict[str, Any]:
            return {
                "console_reachable": True,
                "http_status": 302,
                "console_url": "https://192.0.2.10:30010",
                "error": None,
            }

    async def fake_health(_environment_id: str) -> _Health:
        return _Health()

    service = services.get_openfuyao_service()
    monkeypatch.setattr(service, "health", fake_health)

    response = client.post(
        f"/openfuyao/environments/{environment_id}/health", headers=AUTH
    )

    assert response.status_code == 200
    assert response.json()["console_reachable"] is True
    assert response.json()["proxy_url"] == "http://192.0.2.10:3002/"


def test_unknown_environment_returns_404(tmp_path, monkeypatch) -> None:
    client, _ = _build(tmp_path, monkeypatch)

    response = client.get("/openfuyao/environments/missing", headers=AUTH)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ENVIRONMENT_NOT_FOUND"


def test_recheck_preflight_refreshes_report(tmp_path, monkeypatch) -> None:
    client, services = _build(tmp_path, monkeypatch)
    service = services.get_openfuyao_service()
    service._preflight_runner = lambda: _report(ready=False)

    created = client.post(
        "/openfuyao/environments",
        json={"agent_id": _agent_id(services)},
        headers=AUTH,
    ).json()
    environment_id = created["environment"]["id"]
    assert created["environment"]["status"] == "failed"

    service._preflight_runner = lambda: _report(ready=True)
    response = client.post(
        f"/openfuyao/environments/{environment_id}/preflight", headers=AUTH
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "preflight"
    assert body["error_code"] is None
    assert body["error_message"] is None
    assert body["preflight"]["ready"] is True
    assert body["preflight"]["summary"]["pass"] == 1


def test_recheck_preflight_rejected_while_deploying(tmp_path, monkeypatch) -> None:
    client, services = _build(tmp_path, monkeypatch)
    created = client.post(
        "/openfuyao/environments",
        json={"agent_id": _agent_id(services)},
        headers=AUTH,
    ).json()
    environment_id = created["environment"]["id"]
    services.get_openfuyao_service()._repository.update(
        environment_id, status="bootstrapping"
    )

    response = client.post(
        f"/openfuyao/environments/{environment_id}/preflight", headers=AUTH
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PREFLIGHT_NOT_APPLICABLE"


def test_create_cluster_api_is_disabled_for_console_first_flow(
    tmp_path, monkeypatch
) -> None:
    client, services = _build(tmp_path, monkeypatch)

    response = client.post(
        "/openfuyao/clusters",
        json={
            "agent_id": _agent_id(services),
            "name": "bke-console",
            "nodes": [],
            "confirm": True,
        },
        headers=AUTH,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CLUSTER_CREATE_DISABLED"
