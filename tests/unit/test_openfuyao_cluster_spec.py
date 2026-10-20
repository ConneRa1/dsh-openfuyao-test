"""阶段 2 节点清单：L1 校验与 BKENode 渲染。"""

from __future__ import annotations

import pytest

from witty_service.application.openfuyao.cluster_spec import (
    NodeSpec,
    NodeSpecError,
    normalize_nodes,
    parse_node_argument,
    render_node_docs,
    valid_hostname,
)
from witty_service.domain.openfuyao import ErrorCode, NodeRole

LOCAL_IP = "192.0.2.10"
LOCAL_HOST = "auto-depoly"


def test_valid_hostname_rejects_underscore_and_uppercase() -> None:
    assert valid_hostname("node-2")
    assert valid_hostname("a.b-c")
    assert not valid_hostname("node_2")
    assert not valid_hostname("Node-2")
    assert not valid_hostname("-node")
    assert not valid_hostname("node-")


def test_parse_node_argument_allows_any_order() -> None:
    parsed = parse_node_argument("hostname=n1,role=worker,ip=192.0.2.11")
    assert parsed == {"hostname": "n1", "role": "worker", "ip": "192.0.2.11"}


def test_parse_node_argument_rejects_unknown_field() -> None:
    with pytest.raises(NodeSpecError) as excinfo:
        parse_node_argument("ip=192.0.2.11,password=secret")
    assert excinfo.value.code is ErrorCode.NODE_ROLE_INVALID


def test_normalize_defaults_to_local_master() -> None:
    nodes = normalize_nodes([], local_ip=LOCAL_IP, local_hostname=LOCAL_HOST)
    assert len(nodes) == 1
    assert nodes[0].role is NodeRole.master
    assert nodes[0].is_local
    assert nodes[0].hostname == LOCAL_HOST


def test_normalize_adds_local_master_when_only_workers_given() -> None:
    nodes = normalize_nodes(
        [{"ip": "192.0.2.11", "hostname": "node-2"}],
        local_ip=LOCAL_IP,
        local_hostname=LOCAL_HOST,
    )
    by_ip = {node.ip: node for node in nodes}
    assert by_ip[LOCAL_IP].role is NodeRole.master
    assert by_ip["192.0.2.11"].role is NodeRole.worker


def test_normalize_rejects_remote_master() -> None:
    with pytest.raises(NodeSpecError) as excinfo:
        normalize_nodes(
            [{"ip": "192.0.2.11", "hostname": "node-2", "role": "master"}],
            local_ip=LOCAL_IP,
            local_hostname=LOCAL_HOST,
        )
    assert excinfo.value.code is ErrorCode.NODE_ROLE_INVALID
    assert "master" in excinfo.value.message


def test_normalize_rejects_duplicate_hostname() -> None:
    with pytest.raises(NodeSpecError) as excinfo:
        normalize_nodes(
            [
                {"ip": "192.0.2.11", "hostname": "same"},
                {"ip": "192.0.2.12", "hostname": "same"},
            ],
            local_ip=LOCAL_IP,
            local_hostname=LOCAL_HOST,
        )
    assert excinfo.value.field_name == "hostname"


def test_normalize_rejects_invalid_hostname_before_bke() -> None:
    with pytest.raises(NodeSpecError) as excinfo:
        normalize_nodes(
            [{"ip": "192.0.2.11", "hostname": "node_2"}],
            local_ip=LOCAL_IP,
            local_hostname=LOCAL_HOST,
        )
    assert excinfo.value.code is ErrorCode.HOSTNAME_INVALID


def test_render_node_docs_uses_bke_role_lists() -> None:
    nodes = (
        NodeSpec(ip=LOCAL_IP, hostname=LOCAL_HOST, role=NodeRole.master, is_local=True),
        NodeSpec(ip="192.0.2.11", hostname="node-2", role=NodeRole.worker),
    )
    docs = render_node_docs("bke-multi", nodes, {LOCAL_IP: "p1", "192.0.2.11": "p2"})
    assert [doc["metadata"]["name"] for doc in docs] == [
        "bke-multi-m1",
        "bke-multi-n1",
    ]
    assert docs[0]["spec"]["role"] == ["master/node", "etcd"]
    assert docs[1]["spec"]["role"] == ["node"]
    assert docs[1]["spec"]["hostname"] == "node-2"
    assert docs[0]["metadata"]["namespace"] == "bke-multi"
