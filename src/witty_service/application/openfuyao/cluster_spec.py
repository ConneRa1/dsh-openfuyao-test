"""阶段 2 节点清单：解析、L1 校验、BKENode 渲染。

这一层是**纯函数**，不碰数据库、不碰 SSH、不落盘，因此可以脱离环境单测。
它负责的正是 BKE 不替我们做的事：

- ``spec.hostname`` 由调用方给定，BKE 只用 ``--hostname-override`` 注册 kubelet，
  **不会校验 RFC 1123**（实测 2026-10-20：写 ``worker-1`` 时不报错，OS hostname 不变），
  所以本地必须先查，否则会在 ``InitControlPlane`` 卡住；
- 角色拓扑（本期恰好 1 个 master）、IP/hostname 唯一性、端口范围；
- 凭据只解析出“该用哪个用户名”，密码由 ``node_credentials`` 负责，不进入本层。
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from witty_service.domain.openfuyao import ErrorCode, NodeRole

__all__ = [
    "NodeSpec",
    "NodeSpecError",
    "node_from_mapping",
    "node_name",
    "normalize_nodes",
    "parse_nodes_file",
    "render_node_docs",
    "valid_hostname",
]

#: kubelet 节点名（DNS-1123 subdomain）：小写字母数字、``-``、``.``，首尾必须是字母数字。
_DNS1123_LABEL = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
_MAX_HOSTNAME_LENGTH = 253

#: ``--node`` 允许的键；顺序无关，未知键直接报错而不是静默忽略。
_ALLOWED_KEYS = frozenset({"ip", "hostname", "role", "port", "username"})


class NodeSpecError(ValueError):
    """节点清单不合法；``code`` 直接作为退出码 3 的错误码。"""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        node_ip: str | None = None,
        field_name: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.node_ip = node_ip
        self.field_name = field_name

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "node_ip": self.node_ip,
            "field": self.field_name,
        }


@dataclass(frozen=True, slots=True)
class NodeSpec:
    """一台待加入的节点（不含密码）。

    ``is_local`` 是**推导值**：IP 与运行后端的宿主机一致。本地节点固定是 master，
    远端节点本期只允许 worker（镜像仓库/控制台在本地 AIO 上，跨机当 master
    会引入证书与控制台配置面，见方案 §11.9）。
    """

    ip: str
    hostname: str
    role: NodeRole = NodeRole.worker
    port: int = 22
    #: 空表示“用节点凭据文件里的用户名”
    username: str = ""
    is_local: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ip": self.ip,
            "hostname": self.hostname,
            "role": self.role.value,
            "port": self.port,
            "username": self.username,
            "is_local": self.is_local,
        }


def valid_hostname(value: str) -> bool:
    """RFC 1123 subdomain 校验（kubelet 节点名实际按 DNS label 使用）。"""
    if not value or len(value) > _MAX_HOSTNAME_LENGTH:
        return False
    return all(_DNS1123_LABEL.match(label) for label in value.split("."))


def _valid_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def parse_node_argument(raw: str) -> dict[str, str]:
    """解析 ``--node ip=...,hostname=...,role=master``；``key=value`` 顺序无关。"""
    result: dict[str, str] = {}
    for part in raw.split(","):
        piece = part.strip()
        if not piece:
            continue
        if "=" not in piece:
            raise NodeSpecError(
                ErrorCode.NODE_ROLE_INVALID,
                f"节点参数片段缺少 '='：{piece!r}（格式 ip=...,hostname=...,role=...）",
            )
        key, value = (item.strip() for item in piece.split("=", 1))
        if key not in _ALLOWED_KEYS:
            raise NodeSpecError(
                ErrorCode.NODE_ROLE_INVALID,
                f"未知节点字段 {key!r}；允许：{', '.join(sorted(_ALLOWED_KEYS))}",
            )
        result[key] = value
    return result


def node_from_mapping(data: Mapping[str, Any]) -> NodeSpec:
    """把 CLI/API 的节点映射转成 ``NodeSpec``（只做字段级校验）。"""
    ip = str(data.get("ip") or "").strip()
    hostname = str(data.get("hostname") or "").strip()
    if not ip:
        raise NodeSpecError(ErrorCode.NODE_ROLE_INVALID, "节点缺少 ip", field_name="ip")
    if not _valid_ip(ip):
        raise NodeSpecError(
            ErrorCode.NODE_ROLE_INVALID,
            f"节点 IP 不合法：{ip}",
            node_ip=ip,
            field_name="ip",
        )
    if not hostname:
        raise NodeSpecError(
            ErrorCode.HOSTNAME_INVALID,
            f"节点 {ip} 缺少 hostname",
            node_ip=ip,
            field_name="hostname",
        )
    if not valid_hostname(hostname):
        raise NodeSpecError(
            ErrorCode.HOSTNAME_INVALID,
            f"节点名 {hostname!r} 不满足 RFC 1123（只能小写字母/数字/'-'/'.'，"
            "且首尾为字母数字）；BKE 不会替你校验，请改成 node-2 这类名字",
            node_ip=ip,
            field_name="hostname",
        )

    role_raw = str(data.get("role") or NodeRole.worker.value).strip().lower()
    try:
        role = NodeRole(role_raw)
    except ValueError as exc:
        raise NodeSpecError(
            ErrorCode.NODE_ROLE_INVALID,
            f"节点 {hostname} 的角色不合法：{role_raw}（只允许 master/worker）",
            node_ip=ip,
            field_name="role",
        ) from exc

    port_raw = data.get("port", 22)
    try:
        port = int(port_raw)
    except (TypeError, ValueError) as exc:
        raise NodeSpecError(
            ErrorCode.NODE_ROLE_INVALID,
            f"节点 {hostname} 的端口不合法：{port_raw!r}",
            node_ip=ip,
            field_name="port",
        ) from exc
    if not 1 <= port <= 65535:
        raise NodeSpecError(
            ErrorCode.NODE_ROLE_INVALID,
            f"节点 {hostname} 的端口超出范围：{port}",
            node_ip=ip,
            field_name="port",
        )

    username = str(data.get("username") or "").strip()
    return NodeSpec(ip=ip, hostname=hostname, role=role, port=port, username=username)


def normalize_nodes(
    raw_nodes: Sequence[Mapping[str, Any]] | None,
    *,
    local_ip: str,
    local_hostname: str,
) -> tuple[NodeSpec, ...]:
    """把调用方给的节点补全、校验成最终清单。

    - 未给节点时退化成“本机单节点集群”（本地 master）；
    - 本地节点可省略，会自动补成 master；
    - 本期**恰好 1 个 master，且必须在本机**；其余都是 worker。
    """
    items = [node_from_mapping(item) for item in (raw_nodes or ())]
    local_ip = local_ip.strip()
    if not _valid_ip(local_ip):
        raise NodeSpecError(
            ErrorCode.NODE_ROLE_INVALID,
            f"本机 IP 不合法：{local_ip!r}（可用 OPENFUYAO_HOST 显式指定）",
        )

    if not items:
        items = [
            NodeSpec(
                ip=local_ip,
                hostname=local_hostname,
                role=NodeRole.master,
                is_local=True,
            )
        ]
    elif not any(item.ip == local_ip for item in items):
        # 只给了远端节点时自动补本地 master（方案 §11.2：本地节点可省略）。
        items.insert(
            0,
            NodeSpec(
                ip=local_ip,
                hostname=local_hostname,
                role=NodeRole.master,
                is_local=True,
            ),
        )

    # 本地节点自动补 master，避免调用方漏写角色导致“没有 master”。
    items = [
        NodeSpec(
            ip=item.ip,
            hostname=item.hostname,
            role=NodeRole.master if item.ip == local_ip else item.role,
            port=item.port,
            username=item.username,
            is_local=item.ip == local_ip,
        )
        for item in items
    ]

    masters = [item for item in items if item.role is NodeRole.master]
    if len(masters) != 1:
        raise NodeSpecError(
            ErrorCode.NODE_ROLE_INVALID,
            f"本期只支持 1 个 master，当前有 {len(masters)} 个；"
            "多 master/HA 不在 MVP 范围",
        )
    if not masters[0].is_local:
        raise NodeSpecError(
            ErrorCode.NODE_ROLE_INVALID,
            "master 必须是本机节点（镜像仓库/控制台部署在本机 AIO 上），"
            f"当前 master={masters[0].ip}，本机={local_ip}",
            node_ip=masters[0].ip,
        )

    seen_ips: set[str] = set()
    seen_names: set[str] = set()
    for item in items:
        if item.ip in seen_ips:
            raise NodeSpecError(
                ErrorCode.NODE_ROLE_INVALID,
                f"节点 IP 重复：{item.ip}",
                node_ip=item.ip,
                field_name="ip",
            )
        if item.hostname in seen_names:
            raise NodeSpecError(
                ErrorCode.NODE_ROLE_INVALID,
                f"节点名重复：{item.hostname}",
                node_ip=item.ip,
                field_name="hostname",
            )
        seen_ips.add(item.ip)
        seen_names.add(item.hostname)

    # 稳定顺序：master 在前，其余按输入顺序，便于日志与节点表展示。
    return tuple(
        sorted(items, key=lambda item: (item.role is not NodeRole.master, item.ip))
    )


def parse_nodes_file(payload: Any) -> list[dict[str, Any]]:
    """解析 ``--nodes-file``（JSON 数组，或 ``{"nodes": [...]}``）。"""
    if isinstance(payload, dict):
        payload = payload.get("nodes")
    if not isinstance(payload, list) or not payload:
        raise NodeSpecError(
            ErrorCode.NODE_ROLE_INVALID,
            "节点文件必须是节点数组，或 {\"nodes\": [...]}",
        )
    nodes: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, Mapping):
            raise NodeSpecError(ErrorCode.NODE_ROLE_INVALID, "节点文件元素必须是对象")
        nodes.append({str(key): value for key, value in item.items()})
    return nodes


def node_name(cluster_name: str, spec: NodeSpec, index: int) -> str:
    """BKENode 资源名：``<cluster>-m1`` / ``<cluster>-n1``；K8s 名称需 DNS-1123。"""
    prefix = "m" if spec.role is NodeRole.master else "n"
    suffix = "1" if spec.role is NodeRole.master else str(index)
    raw = f"{cluster_name}-{prefix}{suffix}".lower()
    safe = re.sub(r"[^a-z0-9.-]", "-", raw).strip("-.")
    return safe[:63].rstrip("-.")


@dataclass(frozen=True, slots=True)
class RenderedNode:
    name: str
    spec: NodeSpec
    password: str = field(repr=False)


def render_node_docs(
    cluster_name: str,
    nodes: Sequence[NodeSpec],
    passwords: Mapping[str, str],
) -> list[dict[str, Any]]:
    """渲染 ``nodes.yaml`` 的多文档内容（密码只出现在返回值里，不落日志）。"""
    docs: list[dict[str, Any]] = []
    worker_index = 0
    for spec in nodes:
        if spec.role is NodeRole.master:
            roles = ["master/node", "etcd"]
        else:
            worker_index += 1
            roles = ["node"]
        password = passwords.get(spec.ip)
        if not password:
            raise NodeSpecError(
                ErrorCode.NODE_CREDENTIAL_MISSING,
                f"节点 {spec.ip} 没有可用凭据，无法渲染 BKENode",
                node_ip=spec.ip,
            )
        docs.append(
            {
                "apiVersion": "bke.bocloud.com/v1beta1",
                "kind": "BKENode",
                "metadata": {
                    "name": node_name(cluster_name, spec, worker_index),
                    "namespace": cluster_name,
                    "labels": {"cluster.x-k8s.io/cluster-name": cluster_name},
                },
                "spec": {
                    "hostname": spec.hostname,
                    "ip": spec.ip,
                    "port": str(spec.port),
                    "username": spec.username or "root",
                    "password": password,
                    "role": roles,
                },
            }
        )
    return docs
