"""控制台资源感知：手工集群/应用纳管与 Pod 异常诊断。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from witty_service.application.openfuyao import overview as overview_module
from witty_service.application.openfuyao.helm import HelmRelease
from witty_service.application.openfuyao.kube import ConsoleEndpoint
from witty_service.application.openfuyao.overview import OpenFuyaoObserver
from witty_service.config import OpenFuyaoSettings
from witty_service.persistence.db import (
    create_session_factory,
    create_sqlite_engine,
    init_db,
)
from witty_service.persistence.openfuyao_cluster_repository import (
    OpenFuyaoClusterRepository,
)
from witty_service.persistence.openfuyao_repository import OpenFuyaoRepository

AGENT = "agent-1"
NAMESPACE = "bke-nl"


class _FakeKube:
    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self._cluster = {
            "metadata": {"name": "bke-nl", "namespace": NAMESPACE},
            "spec": {"controlPlaneEndpoint": {"host": "192.0.2.10", "port": 6443}},
            "status": {"ready": True, "phase": "ClusterReady", "conditions": []},
        }
        self._nodes = [
            {
                "metadata": {"name": "bke-nl-m1"},
                "spec": {
                    "ip": "192.0.2.10",
                    "hostname": "auto-depoly",
                    "port": "22",
                    "username": "bkedeploy",
                    "role": ["master/node", "etcd"],
                },
                "status": {"state": "Ready"},
            }
        ]

    async def list_bke_clusters(self) -> list[dict[str, Any]]:
        return [self._cluster]

    async def list_bke_nodes(self, namespace: str, name: str) -> list[dict[str, Any]]:
        del namespace, name
        return self._nodes

    async def get_secret_value(self, namespace: str, name: str, key: str = "value") -> str:
        del namespace, name, key
        return "apiVersion: v1\nkind: Config\n"

    async def get_json(self, argv: list[str], *, timeout: float = 30.0) -> dict[str, Any]:
        del timeout
        if "svc" in argv:
            return {
                "items": [
                    {
                        "metadata": {"name": "nginx", "namespace": "bke-config"},
                        "spec": {
                            "ports": [
                                {"port": 80, "nodePort": 30187},
                            ]
                        },
                    }
                ]
            }
        if "pods" in argv:
            return {
                "items": [
                    {
                        "metadata": {"name": "nginx-abc"},
                        "status": {
                            "phase": "Pending",
                            "initContainerStatuses": [
                                {
                                    "name": "preserve-logs",
                                    "state": {
                                        "waiting": {
                                            "reason": "ImagePullBackOff",
                                            "message": "registry-1.docker.io timeout",
                                        }
                                    },
                                }
                            ],
                            "containerStatuses": [],
                        },
                    }
                ]
            }
        return {}

    async def resolve_console_url(self, *, host: str | None = None) -> ConsoleEndpoint:
        return ConsoleEndpoint(url=f"https://{host}:31616/")


class _FakeHelm:
    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    async def list_all(self) -> list[HelmRelease]:
        return [
            HelmRelease(
                name="nginx",
                namespace="bke-config",
                revision=1,
                status="deployed",
                chart="nginx-25.2.5",
                app_version="1.31.7",
                updated="2026-10-21",
            )
        ]


@pytest.mark.asyncio
async def test_refresh_imports_console_cluster_and_app(tmp_path, monkeypatch) -> None:
    engine = create_sqlite_engine(f"sqlite:///{tmp_path / 'overview.sqlite3'}")
    init_db(engine, auto_create=True)
    repository = OpenFuyaoClusterRepository(create_session_factory(engine))
    environments = OpenFuyaoRepository(create_session_factory(engine))
    monkeypatch.setattr(overview_module, "KubeClient", _FakeKube)
    monkeypatch.setattr(overview_module, "HelmClient", _FakeHelm)
    observer = OpenFuyaoObserver(
        repository=repository,
        environment_repository=environments,
        settings=OpenFuyaoSettings(
            host="192.0.2.10",
            work_dir=str(tmp_path / "work"),
            console_discovery=True,
        ),
        workspace_root=tmp_path,
        local_ip="192.0.2.10",
    )

    result = await observer.refresh(AGENT)

    assert [cluster.name for cluster in result.clusters] == ["bke-nl"]
    assert result.clusters[0].status == "ready"
    assert result.clusters[0].kubeconfig_path
    assert Path(result.clusters[0].kubeconfig_path).is_file()
    assert [(app.release_name, app.namespace) for app in result.apps] == [
        ("nginx", "bke-config")
    ]
    assert result.apps[0].node_port == 30187
    assert result.apps[0].verify_url == "http://192.0.2.10:30187/"
    assert result.console.url == "https://192.0.2.10:31616/"
    issue = next(item for item in result.issues if item.code == "APP_IMAGE_PULL_FAILED")
    assert "nginx" in issue.title
    assert "allowInsecureImages" in issue.remediation

    # 第二次刷新幂等：不能重复插入同名集群/应用。
    again = await observer.refresh(AGENT)
    assert len(again.clusters) == 1
    assert len(again.apps) == 1


@pytest.mark.asyncio
async def test_refresh_marks_console_deleted_cluster(tmp_path, monkeypatch) -> None:
    engine = create_sqlite_engine(f"sqlite:///{tmp_path / 'overview2.sqlite3'}")
    init_db(engine, auto_create=True)
    repository = OpenFuyaoClusterRepository(create_session_factory(engine))
    environments = OpenFuyaoRepository(create_session_factory(engine))
    record = repository.create_cluster(
        agent_id=AGENT,
        environment_id=None,
        name="bke-gone",
        nodes=(),
        status="ready",
        phase="done",
        progress=100,
    )
    monkeypatch.setattr(overview_module, "KubeClient", _FakeKube)
    monkeypatch.setattr(overview_module, "HelmClient", _FakeHelm)
    observer = OpenFuyaoObserver(
        repository=repository,
        environment_repository=environments,
        settings=OpenFuyaoSettings(host="192.0.2.10", work_dir=str(tmp_path / "work")),
        workspace_root=tmp_path,
        local_ip="192.0.2.10",
    )

    result = await observer.refresh(AGENT)

    assert {cluster.name for cluster in result.clusters} == {"bke-nl", "bke-gone"}
    gone = repository.get_cluster(record.id)
    assert gone is not None
    assert gone.status == "failed"
    assert gone.error_code == "CLUSTER_NOT_FOUND"
