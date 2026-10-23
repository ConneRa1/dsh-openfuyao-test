"""阶段 3 AppService：安装状态推进、前置校验与默认验证地址。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from witty_service.application.openfuyao.app_runner import AppResult
from witty_service.application.openfuyao.app_service import AppService, _build_spec
from witty_service.application.openfuyao.cluster_spec import NodeSpec
from witty_service.config import OpenFuyaoSettings
from witty_service.domain.errors import DomainError
from witty_service.domain.openfuyao import ClusterStatus, ErrorCode, NodeRole
from witty_service.persistence.db import (
    create_session_factory,
    create_sqlite_engine,
    init_db,
)
from witty_service.persistence.openfuyao_cluster_repository import (
    OpenFuyaoClusterRepository,
)

LOCAL_IP = "192.0.2.10"


class _FakeRunner:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.on_progress = kwargs.get("on_progress")
        self.cancelled = False

    async def run(self) -> AppResult:
        if self.on_progress:
            self.on_progress("installing", "installing", "helm")
        return AppResult(node_port=32424, verify_url="http://192.0.2.10:32424/", chart="demo")

    async def cancel(self) -> None:
        self.cancelled = True


class _Harness:
    def __init__(self, tmp_path: Path, *, cluster_ready: bool = True) -> None:
        engine = create_sqlite_engine(f"sqlite:///{tmp_path / 'app.sqlite3'}")
        init_db(engine, auto_create=True)
        self.engine = engine
        self.repository = OpenFuyaoClusterRepository(create_session_factory(engine))
        cluster = self.repository.create_cluster(
            agent_id="agent-1",
            environment_id="env-1",
            name="bke-multi",
            nodes=(
                NodeSpec(
                    ip=LOCAL_IP,
                    hostname="auto-depoly",
                    role=NodeRole.master,
                    is_local=True,
                ),
            ),
        )
        self.repository.update_cluster(
            cluster.id,
            status=ClusterStatus.ready if cluster_ready else ClusterStatus.creating,
            endpoint=f"https://{LOCAL_IP}:6443",
            kubeconfig_path="/etc/kubernetes/admin.conf",
        )
        self.service = AppService(
            repository=self.repository,
            settings=OpenFuyaoSettings(work_dir=str(tmp_path / "work")),
            workspace_root=tmp_path,
            runner_factory=lambda **kwargs: _FakeRunner(**kwargs),
        )
        self.cluster_id = cluster.id

    async def wait_deployed(self, app_id: str, timeout: float = 2.0) -> Any:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            record = self.repository.get_app(app_id)
            if record is not None and record.status in {"deployed", "failed"}:
                return record
            await asyncio.sleep(0.01)
        raise AssertionError("app did not finish")

    async def close(self) -> None:
        await self.service.close()
        self.engine.dispose()


def _install_kwargs(tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    chart = tmp_path / "chart"
    chart.mkdir(exist_ok=True)
    values: dict[str, Any] = {
        "agent_id": "agent-1",
        "cluster_name": "bke-multi",
        "release_name": "nginx-demo",
        "namespace": "default",
        "chart_dir": str(chart),
        "repo_url": None,
        "chart": None,
        "chart_version": None,
        "values": {},
        "image": "docker.m.daocloud.io/bitnami/nginx:latest",
        "node_port": 32424,
        "verify_url": None,
        "confirm": True,
    }
    values.update(overrides)
    return values


@pytest.mark.asyncio
async def test_install_deploys_and_sets_default_verify_url(tmp_path) -> None:
    harness = _Harness(tmp_path)
    try:
        result = await harness.service.install(**_install_kwargs(tmp_path))
        assert result.created and result.app is not None
        record = await harness.wait_deployed(result.app.id)
        assert record.status == "deployed"
        assert record.verify_url == "http://192.0.2.10:32424/"
        assert record.node_port == 32424
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_install_requires_confirm(tmp_path) -> None:
    harness = _Harness(tmp_path)
    try:
        result = await harness.service.install(
            **_install_kwargs(tmp_path, confirm=False)
        )
        assert result.needs_confirm
        assert harness.repository.list_apps() == []
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_install_rejects_unready_cluster(tmp_path) -> None:
    harness = _Harness(tmp_path, cluster_ready=False)
    try:
        with pytest.raises(DomainError) as excinfo:
            await harness.service.install(**_install_kwargs(tmp_path))
        assert excinfo.value.code is ErrorCode.CLUSTER_NOT_READY
    finally:
        await harness.close()


def test_build_spec_requires_chart_source(tmp_path) -> None:
    with pytest.raises(DomainError):
        _build_spec(
            release_name="r",
            namespace="default",
            chart_dir=None,
            repo_url=None,
            chart=None,
            chart_version=None,
            values=None,
            image=None,
            node_port=None,
            verify_url=None,
        )


def test_build_spec_rejects_out_of_range_node_port(tmp_path) -> None:
    chart = tmp_path / "chart"
    chart.mkdir()
    with pytest.raises(DomainError):
        _build_spec(
            release_name="r",
            namespace="default",
            chart_dir=str(chart),
            repo_url=None,
            chart=None,
            chart_version=None,
            values=None,
            image=None,
            node_port=1234,
            verify_url=None,
        )


@pytest.mark.asyncio
async def test_app_runner_wires_progress_and_writes_values(tmp_path) -> None:
    """回归：AppRunner 曾漏存 on_progress，导致 run() 立刻 AttributeError。"""
    from witty_service.application.openfuyao.app_runner import (
        AppInstallSpec,
        AppRunner,
    )

    chart = tmp_path / "chart"
    chart.mkdir()
    events: list[tuple[str, str]] = []
    runner = AppRunner(
        app_id="app-1",
        cluster_name="bke-multi",
        kubeconfig_path="/etc/kubernetes/admin.conf",
        spec=AppInstallSpec(
            release_name="nginx-demo",
            namespace="default",
            chart=str(chart),
            image="registry.example/nginx:1.27",
            node_port=32424,
        ),
        settings=OpenFuyaoSettings(work_dir=str(tmp_path / "work")),
        work_dir=tmp_path / "work",
        on_progress=lambda phase, status, _msg: events.append((phase, status.value)),
    )

    async def _fake_helm(values_path):  # type: ignore[no-untyped-def]
        assert values_path is not None and values_path.exists()

    async def _fake_verify_pods() -> None:
        return None

    runner._helm = _fake_helm  # type: ignore[method-assign]
    runner._verify_pods = _fake_verify_pods  # type: ignore[method-assign]
    result = await runner.run()
    assert result.node_port == 32424
    assert [event[0] for event in events] == ["resolving", "installing", "verifying"]
    assert not (tmp_path / "work" / "app-1" / "values.yaml").exists()


@pytest.mark.asyncio
async def test_app_runner_treats_string_true_condition_as_ready(tmp_path) -> None:
    """回归：kubectl 返回的 Pod condition status 是字符串 "True"。"""
    from witty_service.application.openfuyao.app_runner import (
        AppInstallSpec,
        AppRunner,
    )

    runner = AppRunner(
        app_id="app-2",
        cluster_name="bke-multi",
        kubeconfig_path="/tmp/kubeconfig",
        spec=AppInstallSpec(release_name="r", namespace="default", chart="x"),
        settings=OpenFuyaoSettings(work_dir=str(tmp_path / "work")),
        work_dir=tmp_path / "work",
    )

    async def _fake_kubectl(argv):  # type: ignore[no-untyped-def]
        return {
            "items": [
                {
                    "metadata": {"name": "r-abc"},
                    "status": {
                        "phase": "Running",
                        "conditions": [{"type": "Ready", "status": "True"}],
                    },
                }
            ]
        }

    runner._kubectl_json = _fake_kubectl  # type: ignore[method-assign]
    pods = await runner._pods()
    assert pods == [{"name": "r-abc", "phase": "Running", "ready": True}]


class _FakeHelm:
    def __init__(self, entries: list[dict[str, Any]]) -> None:
        self.entries = entries
        self.rolled_back: list[tuple[str, str, int]] = []
        self.uninstalled: list[tuple[str, str]] = []

    async def history(self, release: str, namespace: str) -> list[dict[str, Any]]:
        del release, namespace
        return self.entries

    async def rollback(self, release: str, namespace: str, revision: int) -> None:
        self.rolled_back.append((release, namespace, revision))

    async def uninstall(self, release: str, namespace: str) -> None:
        self.uninstalled.append((release, namespace))


async def _seed_deployed_app(harness: _Harness, tmp_path: Path) -> Any:
    result = await harness.service.install(**_install_kwargs(tmp_path))
    assert result.app is not None
    return await harness.wait_deployed(result.app.id)


@pytest.mark.asyncio
async def test_rollback_uses_previous_revision_and_marks_deployed(tmp_path) -> None:
    harness = _Harness(tmp_path)
    try:
        app = await _seed_deployed_app(harness, tmp_path)
        fake = _FakeHelm(
            [
                {"revision": 1, "status": "superseded"},
                {"revision": 2, "status": "deployed"},
            ]
        )
        harness.service._helm = lambda *_args, **_kwargs: fake  # type: ignore[method-assign]
        updated = await harness.service.rollback(app.id, revision=None, confirm=True)
        assert fake.rolled_back == [("nginx-demo", "default", 1)]
        assert updated.status == "deployed"
        assert updated.progress == 100
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_rollback_without_history_is_rejected(tmp_path) -> None:
    harness = _Harness(tmp_path)
    try:
        app = await _seed_deployed_app(harness, tmp_path)
        fake = _FakeHelm([{"revision": 1, "status": "deployed"}])
        harness.service._helm = lambda *_args, **_kwargs: fake  # type: ignore[method-assign]
        with pytest.raises(DomainError) as excinfo:
            await harness.service.rollback(app.id, revision=None, confirm=True)
        assert excinfo.value.code is ErrorCode.APP_ROLLBACK_FAILED
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_uninstall_deletes_app_record(tmp_path) -> None:
    harness = _Harness(tmp_path)
    try:
        app = await _seed_deployed_app(harness, tmp_path)
        fake = _FakeHelm([])
        harness.service._helm = lambda *_args, **_kwargs: fake  # type: ignore[method-assign]
        removed = await harness.service.uninstall(app.id, confirm=True)
        assert removed.id == app.id
        assert fake.uninstalled == [("nginx-demo", "default")]
        assert harness.repository.get_app(app.id) is None
    finally:
        await harness.close()
