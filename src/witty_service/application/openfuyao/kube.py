"""``kubectl`` 只读观察：BKECluster/BKENode 条件与业务集群节点状态。

阶段 2 的判定不靠解析 ``bke`` 的人类输出，而是看 **CR 的 conditions**（管理集群）
和 **业务集群的 Node 列表**（业务 kubeconfig）。这样即使 ``bke cluster create``
退出码非 0，只要 CR 最终 Ready，我们仍能正确判定（实测：退出码与最终状态不一一对应）。

所有调用都显式传 ``--kubeconfig``，避免 ``bke`` 改写 ``/root/.kube/config`` 后
把管理面与业务面混在一起（2026-10-20 的 reset 事故就是这么发生的）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from witty_service.application.openfuyao.process import (
    CommandError,
    CommandResult,
    CommandRunner,
)

__all__ = [
    "ClusterObservation",
    "KubeClient",
    "NodeObservation",
]

#: BKECluster 里可能表示“集群可用”的条件类型（不同 BKE 版本命名略有差异）。
_CLUSTER_READY_TYPES = frozenset({"Ready", "ClusterReady"})
_CLUSTER_HEALTHY_TYPES = frozenset({"Healthy"})


@dataclass(frozen=True, slots=True)
class ClusterObservation:
    found: bool
    ready: bool
    healthy: bool
    message: str = ""
    conditions: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    @property
    def failed_message(self) -> str:
        for condition in self.conditions:
            if condition.get("status") not in (True, "True"):
                text = condition.get("message") or condition.get("reason")
                if text:
                    return str(text)
        return self.message


@dataclass(frozen=True, slots=True)
class NodeObservation:
    name: str
    ready: bool
    status: str = ""
    message: str = ""


class KubeClient:
    """薄封装：一次 ``kubectl ... -o json``，失败返回 ``None``。"""

    def __init__(self, commands: CommandRunner, kubeconfig: str) -> None:
        self._commands = commands
        self._kubeconfig = kubeconfig

    @property
    def kubeconfig(self) -> str:
        return self._kubeconfig

    async def _get_json(
        self, argv: list[str], *, timeout: float = 30.0
    ) -> dict[str, Any] | None:
        try:
            result = await self._commands.run_capture(
                ["kubectl", "--kubeconfig", self._kubeconfig, *argv], timeout=timeout
            )
        except CommandError:
            return None
        if result.returncode != 0:
            return None
        try:
            payload = json.loads(result.output)
        except ValueError:
            return None
        return payload if isinstance(payload, dict) else None

    async def observe_cluster(
        self, namespace: str, name: str
    ) -> ClusterObservation:
        payload = await self._get_json(
            ["-n", namespace, "get", "bkecluster", name, "-o", "json"]
        )
        if payload is None:
            return ClusterObservation(found=False, ready=False, healthy=False)
        conditions = _conditions(payload)
        ready = any(
            _truthy(item.get("status"))
            and str(item.get("type")) in _CLUSTER_READY_TYPES
            for item in conditions
        )
        healthy = any(
            _truthy(item.get("status"))
            and str(item.get("type")) in _CLUSTER_HEALTHY_TYPES
            for item in conditions
        )
        status = payload.get("status") or {}
        if isinstance(status, dict) and status.get("ready") is True:
            ready = True
        return ClusterObservation(
            found=True,
            ready=ready,
            healthy=healthy,
            message=_first_message(conditions),
            conditions=conditions,
        )

    async def observe_bke_nodes(
        self, namespace: str, cluster_name: str
    ) -> dict[str, NodeObservation]:
        payload = await self._get_json(
            [
                "-n",
                namespace,
                "get",
                "bkenode",
                "-l",
                f"cluster.x-k8s.io/cluster-name={cluster_name}",
                "-o",
                "json",
            ]
        )
        if payload is None:
            return {}
        result: dict[str, NodeObservation] = {}
        for item in payload.get("items") or []:
            if not isinstance(item, dict):
                continue
            metadata = item.get("metadata") or {}
            name = str(metadata.get("name") or "")
            spec = item.get("spec") or {}
            conditions = _conditions(item)
            ready = any(
                _truthy(condition.get("status"))
                and str(condition.get("type")) in _CLUSTER_READY_TYPES
                for condition in conditions
            )
            result[name] = NodeObservation(
                name=name,
                ready=ready,
                status=str(spec.get("ip") or ""),
                message=_first_message(conditions),
            )
        return result

    async def observe_kube_nodes(self) -> dict[str, NodeObservation]:
        payload = await self._get_json(["get", "nodes", "-o", "json"])
        if payload is None:
            return {}
        result: dict[str, NodeObservation] = {}
        for item in payload.get("items") or []:
            if not isinstance(item, dict):
                continue
            metadata = item.get("metadata") or {}
            name = str(metadata.get("name") or "")
            conditions = _conditions(item)
            ready_condition = next(
                (c for c in conditions if str(c.get("type")) == "Ready"), None
            )
            result[name] = NodeObservation(
                name=name,
                ready=bool(ready_condition and _truthy(ready_condition.get("status"))),
                status=str((ready_condition or {}).get("reason") or ""),
                message=str((ready_condition or {}).get("message") or ""),
            )
        return result

    async def delete_cluster(self, namespace: str, name: str) -> CommandResult:
        return await self._commands.run_capture(
            [
                "kubectl",
                "--kubeconfig",
                self._kubeconfig,
                "-n",
                namespace,
                "delete",
                "bkecluster",
                name,
                "--ignore-not-found",
                "--timeout=120s",
            ],
            timeout=150.0,
        )


def _conditions(payload: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    status = payload.get("status") or {}
    if not isinstance(status, dict):
        return ()
    conditions = status.get("conditions") or []
    return tuple(item for item in conditions if isinstance(item, dict))


def _truthy(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.lower() == "true")


def _first_message(conditions: tuple[dict[str, Any], ...]) -> str:
    for condition in conditions:
        if condition.get("status") not in (True, "True"):
            text = condition.get("message") or condition.get("reason")
            if text:
                return str(text)
    return ""
