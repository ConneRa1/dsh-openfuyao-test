"""渲染 BKE 的 ``cluster.yaml`` / ``nodes.yaml``。

集群配置模板来自 ``witty_service/data/openfuyao/cluster-template.yaml``（2026-10-20
实跑通过的 ``bke-multi`` 配置），只替换与本次集群相关的少量字段：

- ``metadata.name/namespace`` = 集群名；
- 仓库 IP（``httpRepo`` / ``imageRepo`` / ``customExtra.host`` 等）= master 节点 IP；
- 节点文档由 ``cluster_spec.render_node_docs`` 生成（含密码，只在临时目录里）。

目录权限 0700、文件 0600，执行后由调用方 ``finally`` 删除：密码不能留在磁盘上。
"""

from __future__ import annotations

import copy
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from witty_service.application.openfuyao.cluster_spec import (
    NodeSpec,
    render_node_docs,
)

__all__ = [
    "RenderedBundle",
    "build_bundle",
    "cleanup_bundle",
    "template_cluster_doc",
    "write_bundle",
]

_TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "openfuyao"
    / "cluster-template.yaml"
)


@dataclass(frozen=True, slots=True)
class RenderedBundle:
    cluster_yaml: str
    nodes_yaml: str


def template_cluster_doc() -> dict[str, Any]:
    payload = yaml.safe_load(_TEMPLATE.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"集群模板损坏：{_TEMPLATE}")
    return payload


def build_cluster_doc(
    cluster_name: str,
    *,
    master_ip: str,
) -> dict[str, Any]:
    """按集群名/主节点 IP 生成 ``BKECluster`` 文档。"""
    doc = copy.deepcopy(template_cluster_doc())
    doc.pop("status", None)
    metadata = doc.setdefault("metadata", {})
    metadata.pop("creationTimestamp", None)
    metadata["name"] = cluster_name
    metadata["namespace"] = cluster_name

    spec = doc.setdefault("spec", {})
    cluster_config = spec.setdefault("clusterConfig", {})
    cluster = cluster_config.setdefault("cluster", {})
    for key in ("httpRepo", "imageRepo"):
        repo = cluster.setdefault(key, {})
        repo["ip"] = master_ip
    custom = cluster_config.setdefault("customExtra", {})
    custom["host"] = master_ip
    for key in ("otherChartIp", "otherRepoIp"):
        if key in custom:
            custom[key] = master_ip
    return doc


def build_bundle(
    cluster_name: str,
    nodes: tuple[NodeSpec, ...],
    *,
    passwords: dict[str, str],
) -> RenderedBundle:
    master = next(node for node in nodes if node.role.value == "master")
    cluster_doc = build_cluster_doc(cluster_name, master_ip=master.ip)
    node_docs = render_node_docs(cluster_name, nodes, passwords)
    return RenderedBundle(
        cluster_yaml=yaml.safe_dump(
            cluster_doc, allow_unicode=True, sort_keys=False
        ),
        nodes_yaml=yaml.safe_dump_all(
            node_docs, allow_unicode=True, sort_keys=False
        ),
    )


def write_bundle(directory: Path, bundle: RenderedBundle) -> tuple[Path, Path]:
    """把 bundle 落成 0600 文件；目录 0700。返回 (cluster.yaml, nodes.yaml)。"""
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)
    cluster_path = directory / "cluster.yaml"
    nodes_path = directory / "nodes.yaml"
    _write_secret(cluster_path, bundle.cluster_yaml)
    _write_secret(nodes_path, bundle.nodes_yaml)
    return cluster_path, nodes_path


def cleanup_bundle(directory: Path) -> None:
    shutil.rmtree(directory, ignore_errors=True)


def _write_secret(path: Path, content: str) -> None:
    # 先以 0600 打开再写，避免 umask 窗口期出现 0644。
    descriptor = path.open("w", encoding="utf-8")
    try:
        descriptor.write(content)
    finally:
        descriptor.close()
    path.chmod(0o600)
