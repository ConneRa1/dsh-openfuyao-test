"""Headless sidecar smoke tests: auth, empty database, ephemeral agent."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from witty_service.sidecar.app import create_sidecar_app
from witty_service.sidecar.config import SidecarConfig
from witty_service.sidecar.services import SidecarAgentLookup, SidecarServices


def _config(tmp_path: Path, token: str = "sidecar-test-token") -> SidecarConfig:
    return SidecarConfig(
        token=token,
        db_path=tmp_path / "sidecar.sqlite3",
        workspace_root=tmp_path / "workspace",
        agent_id="openfuyao-deployer",
        allow_ephemeral_agent=True,
    )


@pytest.fixture()
def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, str]]:
    token = "sidecar-test-token"
    config = _config(tmp_path, token)
    monkeypatch.setenv("AUTH_TOKEN", token)
    monkeypatch.setenv("WITTY_DATABASE_URL", config.database_url)
    monkeypatch.setenv("WITTY_WORKSPACE_ROOT", str(config.workspace_root))
    monkeypatch.setenv("OPENFUYAO_WORK_DIR", str(config.workspace_root / "openfuyao"))

    services = SidecarServices(config)
    app = create_sidecar_app(services, config=config, port=12345)
    with TestClient(app) as test_client:
        yield test_client, token


def test_healthz_is_unauthenticated(client: tuple[TestClient, str]) -> None:
    test_client, _ = client
    response = test_client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["sidecar"] == 1


def test_openfuyao_routes_require_bearer(client: tuple[TestClient, str]) -> None:
    test_client, token = client
    assert test_client.get("/openfuyao/environments").status_code == 401
    response = test_client.get(
        "/openfuyao/environments",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json() == []


def test_info_does_not_leak_token(client: tuple[TestClient, str]) -> None:
    test_client, token = client
    response = test_client.get("/sidecar/info")
    assert response.status_code == 200
    assert token not in response.text


def test_apply_environment_wires_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The production env wiring is what the shared config layer reads."""
    config = _config(tmp_path)
    for key in (
        "AUTH_TOKEN",
        "WITTY_DATABASE_URL",
        "WITTY_DATABASE_AUTO_CREATE",
        "WITTY_WORKSPACE_ROOT",
        "OPENFUYAO_WORK_DIR",
        "WITTY_LOG_LEVEL",
    ):
        monkeypatch.delenv(key, raising=False)

    config.apply_environment()

    assert os.environ["AUTH_TOKEN"] == config.token
    assert os.environ["WITTY_DATABASE_URL"] == config.database_url
    assert os.environ["WITTY_DATABASE_AUTO_CREATE"] == "true"
    assert os.environ["WITTY_WORKSPACE_ROOT"] == str(config.workspace_root)
    assert os.environ["OPENFUYAO_WORK_DIR"] == str(config.workspace_root / "openfuyao")
    assert os.environ["WITTY_LOG_LEVEL"] == config.log_level


def test_ephemeral_agent_lookup(tmp_path: Path) -> None:
    config = _config(tmp_path)
    services = SidecarServices(config)
    try:
        lookup = SidecarAgentLookup(
            services.session_factory,
            allow_ephemeral=True,
            ephemeral_agent_id="plugin-agent",
        )
        agent = lookup.get_agent("plugin-agent")
        assert agent is not None
        assert agent.id == "plugin-agent"
        assert lookup.get_agent("other-agent") is None

        strict = SidecarAgentLookup(
            services.session_factory,
            allow_ephemeral=False,
            ephemeral_agent_id="plugin-agent",
        )
        assert strict.get_agent("plugin-agent") is None
    finally:
        asyncio.run(services.close())
