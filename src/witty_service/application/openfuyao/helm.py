"""``helm`` 只读查询与受控变更。

阶段 3 的“感知”必须看到用户在业务控制台手工安装的 release；阶段 3 的“回滚/卸载”
也必须操作同一份 Helm release，而不是另建一套应用记录。所有命令显式传
``--kubeconfig``，避免当前 context 指向别的集群（阶段 1 的 reset 事故同源）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from witty_service.application.openfuyao.process import (
    CommandCancelled,
    CommandError,
    CommandResult,
    CommandRunner,
    CommandTimeout,
)

__all__ = ["HelmClient", "HelmError", "HelmRelease", "parse_chart"]

_CHART_RE = re.compile(r"^(.+?)-(\d+\.\d+\.\d+.*)$")


class HelmError(RuntimeError):
    def __init__(self, message: str, *, output: str | None = None) -> None:
        super().__init__(message)
        self.output = output or ""


@dataclass(frozen=True, slots=True)
class HelmRelease:
    name: str
    namespace: str
    revision: int
    status: str
    chart: str
    app_version: str
    updated: str

    @property
    def chart_name(self) -> str:
        return parse_chart(self.chart)[0]

    @property
    def chart_version(self) -> str | None:
        return parse_chart(self.chart)[1]


def parse_chart(chart: str) -> tuple[str, str | None]:
    """``nginx-25.2.5`` → ``("nginx", "25.2.5")``；无法拆分时整串作为名字。"""
    match = _CHART_RE.match(chart.strip())
    if match is None:
        return chart, None
    return match.group(1), match.group(2)


class HelmClient:
    def __init__(
        self,
        commands: CommandRunner,
        kubeconfig: str,
        *,
        timeout: float = 120.0,
    ) -> None:
        self._commands = commands
        self._kubeconfig = kubeconfig
        self._timeout = timeout

    def _argv(self, *args: str) -> list[str]:
        return ["helm", "--kubeconfig", self._kubeconfig, *args]

    async def _run(
        self, argv: list[str], *, timeout: float | None = None
    ) -> CommandResult:
        try:
            result = await self._commands.run_capture(
                argv, timeout=timeout or self._timeout
            )
        except CommandCancelled as exc:
            raise HelmError("helm 命令已取消", output=exc.output) from exc
        except CommandTimeout as exc:
            raise HelmError("helm 命令超时", output=exc.output) from exc
        except CommandError as exc:
            raise HelmError(str(exc), output=exc.output) from exc
        if result.returncode != 0:
            raise HelmError(
                f"helm 执行失败（exit={result.returncode}）", output=result.output
            )
        return result

    async def list_all(self) -> list[HelmRelease]:
        result = await self._run(self._argv("list", "--all-namespaces", "-o", "json"))
        try:
            payload = json.loads(result.output or "[]")
        except ValueError as exc:
            raise HelmError("helm list 返回的不是 JSON", output=result.output) from exc
        if not isinstance(payload, list):
            return []
        releases: list[HelmRelease] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            try:
                releases.append(
                    HelmRelease(
                        name=str(item.get("name") or ""),
                        namespace=str(item.get("namespace") or ""),
                        revision=int(item.get("revision") or 0),
                        status=str(item.get("status") or ""),
                        chart=str(item.get("chart") or ""),
                        app_version=str(item.get("app_version") or ""),
                        updated=str(item.get("updated") or ""),
                    )
                )
            except (TypeError, ValueError):
                continue
        return releases

    async def history(self, release: str, namespace: str) -> list[dict[str, Any]]:
        result = await self._run(
            self._argv("history", release, "-n", namespace, "-o", "json")
        )
        try:
            payload = json.loads(result.output or "[]")
        except ValueError as exc:
            raise HelmError("helm history 返回的不是 JSON", output=result.output) from exc
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    async def rollback(
        self, release: str, namespace: str, revision: int, *, timeout: float = 300.0
    ) -> None:
        await self._run(
            self._argv(
                "rollback",
                release,
                str(revision),
                "-n",
                namespace,
                "--wait",
                "--timeout",
                f"{int(timeout)}s",
            ),
            timeout=timeout + 30,
        )

    async def uninstall(
        self, release: str, namespace: str, *, timeout: float = 300.0
    ) -> None:
        await self._run(
            self._argv(
                "uninstall",
                release,
                "-n",
                namespace,
                "--wait",
                "--timeout",
                f"{int(timeout)}s",
            ),
            timeout=timeout + 30,
        )
