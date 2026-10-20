"""阶段 2 渲染：模板替换、0600 落盘与清理。"""

from __future__ import annotations

import stat

import yaml

from witty_service.application.openfuyao.cluster_render import (
    build_bundle,
    cleanup_bundle,
    write_bundle,
)
from witty_service.application.openfuyao.cluster_spec import NodeSpec
from witty_service.domain.openfuyao import NodeRole

LOCAL_IP = "192.0.2.10"


def _nodes() -> tuple[NodeSpec, ...]:
    return (
        NodeSpec(ip=LOCAL_IP, hostname="auto-depoly", role=NodeRole.master, is_local=True),
        NodeSpec(ip="192.0.2.11", hostname="node-2", role=NodeRole.worker),
    )


def test_build_bundle_replaces_name_and_repo_ip() -> None:
    bundle = build_bundle(
        "bke-multi", _nodes(), passwords={LOCAL_IP: "p1", "192.0.2.11": "p2"}
    )
    cluster = yaml.safe_load(bundle.cluster_yaml)
    assert cluster["metadata"]["name"] == "bke-multi"
    assert cluster["metadata"]["namespace"] == "bke-multi"
    cluster_config = cluster["spec"]["clusterConfig"]
    assert cluster_config["cluster"]["httpRepo"]["ip"] == LOCAL_IP
    assert cluster_config["cluster"]["imageRepo"]["ip"] == LOCAL_IP
    assert cluster_config["customExtra"]["host"] == LOCAL_IP
    assert "status" not in cluster

    nodes = list(yaml.safe_load_all(bundle.nodes_yaml))
    assert len(nodes) == 2
    assert nodes[1]["spec"]["password"] == "p2"


def test_write_bundle_is_0600_and_cleanup_removes_dir(tmp_path) -> None:
    bundle = build_bundle(
        "bke-multi", _nodes(), passwords={LOCAL_IP: "p1", "192.0.2.11": "p2"}
    )
    directory = tmp_path / "bundle"
    cluster_path, nodes_path = write_bundle(directory, bundle)
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    for path in (cluster_path, nodes_path):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    cleanup_bundle(directory)
    assert not directory.exists()
