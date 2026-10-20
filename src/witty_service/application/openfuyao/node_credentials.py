"""节点凭据：只存在主机侧文件，永不出现在 API/CLI/日志里。

BKENode 当前只支持用户名/密码（不支持 SSH key），所以密码必须能传给 ``bke``；
为了不让密码进入 Agent 上下文或数据库，采用与方案 §3 一致的做法：

- 文件默认 ``/var/lib/witty-service/.witty/openfuyao/nodes.cred``（0600）；
- 按 **IP** 索引：``{"192.168.122.151": {"username": "root", "password": "..."}}``；
- API/CLI 只传 IP/节点名/角色，后端在这里解析密码并渲染进 0600 的临时 yaml；
- 渲染目录执行后删除（``cluster_runner`` 的 ``finally``）。

文件不存在或缺少某台节点时，绝不“猜一个密码”：直接 ``NODE_CREDENTIAL_MISSING``，
并把文件路径写进错误信息，便于用户补配置。
"""

from __future__ import annotations

import logging
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from witty_service.application.openfuyao.cluster_spec import NodeSpec, NodeSpecError
from witty_service.domain.openfuyao import ErrorCode

logger = logging.getLogger(__name__)

__all__ = ["CredentialStore", "NodeCredential"]


@dataclass(frozen=True, slots=True)
class NodeCredential:
    username: str
    password: str

    def __repr__(self) -> str:  # pragma: no cover - 防手滑把密码打进日志
        return f"NodeCredential(username={self.username!r}, password='***')"


class CredentialStore:
    """按 IP 查密码；支持“映射”和“数组”两种 YAML 写法。"""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> dict[str, NodeCredential]:
        if not self._path.exists():
            return {}
        self._warn_if_world_readable()
        try:
            payload: Any = yaml.safe_load(self._path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise NodeSpecError(
                ErrorCode.NODE_CREDENTIAL_MISSING,
                f"节点凭据文件不是合法 YAML：{self._path}（{exc}）",
            ) from exc
        return _parse_payload(payload)

    def resolve(self, spec: NodeSpec) -> NodeCredential:
        entries = self.load()
        entry = entries.get(spec.ip)
        if entry is None:
            raise NodeSpecError(
                ErrorCode.NODE_CREDENTIAL_MISSING,
                f"节点 {spec.ip}（{spec.hostname}）缺少凭据；"
                f"请在 {self._path} 中按 IP 增加 username/password（0600）",
                node_ip=spec.ip,
            )
        return NodeCredential(
            username=spec.username or entry.username,
            password=entry.password,
        )

    def resolve_all(self, specs: tuple[NodeSpec, ...]) -> dict[str, NodeCredential]:
        return {spec.ip: self.resolve(spec) for spec in specs}

    def _warn_if_world_readable(self) -> None:
        try:
            mode = self._path.stat().st_mode
        except OSError:
            return
        if mode & (stat.S_IRGRP | stat.S_IROTH):
            logger.warning(
                "openFuyao 节点凭据文件权限过宽（%s）：建议 chmod 600 %s",
                oct(stat.S_IMODE(mode)),
                self._path,
            )


def _parse_payload(payload: Any) -> dict[str, NodeCredential]:
    if payload is None:
        return {}
    entries: dict[str, NodeCredential] = {}

    if isinstance(payload, dict) and isinstance(payload.get("nodes"), list):
        payload = payload["nodes"]

    if isinstance(payload, dict):
        for ip, value in payload.items():
            if not isinstance(value, dict):
                raise _invalid("节点凭据条目必须是对象：{ip: {username, password}}")
            entries[str(ip)] = _credential_from_mapping(value)
        return entries

    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict) or not item.get("ip"):
                raise _invalid("节点凭据数组元素必须包含 ip")
            entries[str(item["ip"])] = _credential_from_mapping(item)
        return entries

    raise _invalid("节点凭据文件顶层必须是映射或数组")


def _credential_from_mapping(value: dict[str, Any]) -> NodeCredential:
    password = value.get("password")
    if not password or not isinstance(password, str):
        raise _invalid("节点凭据缺少 password")
    username = value.get("username") or "root"
    return NodeCredential(username=str(username), password=str(password))


def _invalid(message: str) -> NodeSpecError:
    return NodeSpecError(ErrorCode.NODE_CREDENTIAL_MISSING, message)
