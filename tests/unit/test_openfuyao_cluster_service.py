"""阶段 2 ClusterService：幂等、冲突、凭据与状态推进。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from witty_service.application.openfuyao.cluster_runner import (
    ClusterResult,
    PreflightFailure,
    PreflightOutcome,
)
from witty_service.application.openfuyao.cluster_service import ClusterService
from witty_service.config import OpenFuyaoSettings
from witty_service.domain.errors import DomainError
from witty_service.domain.openfuyao import ClusterStatus, ErrorCode
from witty_service.persistence.db import (
    create_session_factory,
    create_sqlite_engine,
    init_db,
)
from witty_service.persistence.openfuyao_cluster_repository import (
    OpenFuyaoClusterRepository,
)

LOCAL_IP = "192.0.2.10"
WORKER_IP = "192.0.2.11"


def _cred_file(tmp_path: Path, *, worker: bool = True) -> Path:
    lines = [f'"{LOCAL_IP}": {{username: bkedeploy, password: p1}}']
    if worker:
        lines.append(f'"{WORKER_IP}": {{username: root, password: p2}}')
    path = tmp_path / "nodes.cred"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


class _EnvironmentRepository:
    def list(self, *, agent_id: str | None = None) -> list[Any]:
        del agent_id
        return [SimpleNamespace(id="env-1", status="ready")]


class _FakeRunner:
    def __init__(self, **kwargs: Any) -> None:
        self.on_progress = kwargs.get("on_progress")
        self.on_node = kwargs.get("on_node")
        self.cancelled = False
        self.fail_code: ErrorCode | None = None

    async def run(self) -> ClusterResult:
        if self.fail_code is not None:
            from witty_service.application.openfuyao.cluster_runner import (
                ClusterError,
            )

            raise ClusterError(
                self.fail_code, "boom", phase="wait_ready", node_ip=WORKER_IP
            )
        for ip in (LOCAL_IP, WORKER_IP):
            if self.on_node:
                self.on_node(ip, "ready", None, "Ready")
        return ClusterResult(
            kubeconfig_path="/etc/kubernetes/admin.conf",
            endpoint=f"https://{LOCAL_IP}:6443",
            node_ips=(LOCAL_IP, WORKER_IP),
        )

    async def preflight_only(self) -> PreflightOutcome:
        failure = PreflightFailure(
            rule_id="CLUSTER-RES-MEMORY",
            subject="kube-n1",
            status="fail",
            node_ip=WORKER_IP,
            code=ErrorCode.MEMORY_INSUFFICIENT,
            message="内存不足",
            remediation="扩容",
        )
        return PreflightOutcome(payload={"overall": "FAIL"}, failures=(failure,), tolerated=())

    async def cancel(self) -> None:
        self.cancelled = True


class _Harness:
    def __init__(self, tmp_path: Path, *, worker_cred: bool = True) -> None:
        engine = create_sqlite_engine(f"sqlite:///{tmp_path / 'cluster.sqlite3'}")
        init_db(engine, auto_create=True)
        self.engine = engine
        self.repository = OpenFuyaoClusterRepository(create_session_factory(engine))
        self.runners: list[_FakeRunner] = []

        def factory(**kwargs: Any) -> _FakeRunner:
            runner = _FakeRunner(**kwargs)
            self.runners.append(runner)
            return runner

        self.service = ClusterService(
            repository=self.repository,
            environment_repository=_EnvironmentRepository(),
            settings=OpenFuyaoSettings(
                host=LOCAL_IP,
                work_dir=str(tmp_path / "work"),
                nodes_credential_file=str(
                    _cred_file(tmp_path, worker=worker_cred)
                ),
            ),
            workspace_root=tmp_path,
            runner_factory=factory,
            local_hostname="auto-depoly",
            local_ip=LOCAL_IP,
        )

    def nodes(self) -> list[dict[str, Any]]:
        return [
            {"ip": LOCAL_IP, "hostname": "auto-depoly", "role": "master"},
            {"ip": WORKER_IP, "hostname": "node-2", "role": "worker"},
        ]

    async def wait_status(self, cluster_id: str, status: str, timeout: float = 2.0) -> Any:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            record = self.repository.get_cluster(cluster_id)
            if record is not None and record.status == status:
                return record
            await asyncio.sleep(0.01)
        raise AssertionError(f"cluster not {status}")

    async def close(self) -> None:
        await self.service.close()
        self.engine.dispose()


@pytest.mark.asyncio
async def test_create_requires_confirm(tmp_path) -> None:
    harness = _Harness(tmp_path)
    try:
        result = await harness.service.create_cluster(
            agent_id="agent-1", name="bke-multi", raw_nodes=harness.nodes(), confirm=False
        )
        assert result.needs_confirm
        assert harness.repository.list_clusters() == []
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_create_reaches_ready_and_marks_nodes(tmp_path) -> None:
    harness = _Harness(tmp_path)
    try:
        result = await harness.service.create_cluster(
            agent_id="agent-1", name="bke-multi", raw_nodes=harness.nodes(), confirm=True
        )
        assert result.created and result.cluster is not None
        record = await harness.wait_status(result.cluster.id, ClusterStatus.ready)
        assert record.endpoint == f"https://{LOCAL_IP}:6443"
        assert {node.status for node in harness.service.nodes(record.id)} == {"ready"}
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_create_is_idempotent_for_same_nodes(tmp_path) -> None:
    harness = _Harness(tmp_path)
    try:
        first = await harness.service.create_cluster(
            agent_id="agent-1", name="bke-multi", raw_nodes=harness.nodes(), confirm=True
        )
        await harness.wait_status(first.cluster.id, ClusterStatus.ready)
        second = await harness.service.create_cluster(
            agent_id="agent-1", name="bke-multi", raw_nodes=harness.nodes(), confirm=True
        )
        assert second.created is False
        assert second.cluster is not None and second.cluster.status == ClusterStatus.ready
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_same_name_different_nodes_conflicts(tmp_path) -> None:
    harness = _Harness(tmp_path)
    try:
        first = await harness.service.create_cluster(
            agent_id="agent-1", name="bke-multi", raw_nodes=harness.nodes(), confirm=True
        )
        await harness.wait_status(first.cluster.id, ClusterStatus.ready)
        with pytest.raises(DomainError) as excinfo:
            await harness.service.create_cluster(
                agent_id="agent-1",
                name="bke-multi",
                raw_nodes=[{"ip": LOCAL_IP, "hostname": "auto-depoly", "role": "master"}],
                confirm=True,
            )
        assert excinfo.value.code is ErrorCode.CONFLICT_EXISTS
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_missing_worker_credential_fails_before_creating(tmp_path) -> None:
    harness = _Harness(tmp_path, worker_cred=False)
    try:
        with pytest.raises(DomainError) as excinfo:
            await harness.service.create_cluster(
                agent_id="agent-1", name="bke-multi", raw_nodes=harness.nodes(), confirm=True
            )
        assert excinfo.value.code is ErrorCode.NODE_CREDENTIAL_MISSING
        assert harness.repository.list_clusters() == []
    finally:
        await harness.close()


@pytest.mark.asyncio
async def test_preflight_reports_failure(tmp_path) -> None:
    harness = _Harness(tmp_path)
    try:
        result = await harness.service.preflight(
            agent_id="agent-1", raw_nodes=harness.nodes()
        )
        assert result.ready is False
        assert result.failures[0].code is ErrorCode.MEMORY_INSUFFICIENT
    finally:
        await harness.close()
