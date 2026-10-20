"""阶段 3 执行器：``helm upgrade --install`` + Pod/URL 验证。

选择直接调用 ``helm`` 而不是应用市场 REST：市场 API 需要控制台会话/仓库 ID，
而 helm release 本身就是市场看到的同一份数据（实跑验证：市场 API 能看到 helm
安装的 release）。首版支持三种 chart 来源：

- ``--chart-dir``：本地目录（离线/内网最稳，本次验收用它）；
- ``--repo-url`` + ``--chart`` + ``--version``：经典 HTTP 仓库；
- ``--chart`` 以 ``oci://`` 开头：OCI 仓库。

镜像与 NodePort 通过 values 注入（``image.repository/image.tag``、``service.nodePort``），
这是 Helm chart 的通用约定；对 Bitnami 类 chart 额外允许非官方镜像
（``global.security.allowInsecureImages=true``），避免 ``docker.m.daocloud.io`` 镜像被拒。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml

from witty_service.application.openfuyao.log_tail import truncate_log
from witty_service.application.openfuyao.process import (
    CommandCancelled,
    CommandError,
    CommandResult,
    CommandRunner,
    CommandTimeout,
)
from witty_service.config import OpenFuyaoSettings
from witty_service.domain.openfuyao import AppStatus, ErrorCode

logger = logging.getLogger(__name__)

__all__ = [
    "AppCancelled",
    "AppError",
    "AppInstallSpec",
    "AppResult",
    "AppRunner",
]

ProgressCallback = Callable[[str, AppStatus, str], None]

#: helm 失败输出里能判定为“拉 chart 失败”的关键词（→ CHART_PULL_FAILED）
_PULL_MARKERS = (
    "failed to download",
    "failed to fetch",
    "not found",
    "connection refused",
    "connection reset",
    "no such host",
    "timeout",
    "401 unauthorized",
)


class AppError(RuntimeError):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        phase: str,
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.phase = phase
        self.detail = detail


class AppCancelled(AppError):
    def __init__(self, *, phase: str) -> None:
        super().__init__(ErrorCode.APP_CANCELLED, "应用安装已取消", phase=phase)


@dataclass(frozen=True, slots=True)
class AppInstallSpec:
    release_name: str
    namespace: str
    chart: str
    repo_url: str | None = None
    chart_version: str | None = None
    values: dict[str, Any] = field(default_factory=dict)
    image: str | None = None
    node_port: int | None = None
    verify_url: str | None = None
    verify_status: int = 200


@dataclass(frozen=True, slots=True)
class AppResult:
    node_port: int | None
    verify_url: str | None
    chart: str


class AppRunner:
    def __init__(
        self,
        *,
        app_id: str,
        cluster_name: str,
        kubeconfig_path: str,
        spec: AppInstallSpec,
        settings: OpenFuyaoSettings,
        work_dir: Path,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        self._app_id = app_id
        self._cluster_name = cluster_name
        self._kubeconfig = kubeconfig_path
        self._spec = spec
        self._settings = settings
        self._on_progress = on_progress
        self._run_dir = work_dir / app_id
        self._log_path = self._run_dir / "app.log"
        self._log_handle: Any = None
        self._commands: CommandRunner | None = None
        self._cancelled = False

    @property
    def log_path(self) -> Path:
        return self._log_path

    async def run(self) -> AppResult:
        self._run_dir.mkdir(parents=True, exist_ok=True)
        truncate_log(self._log_path)
        self._log_handle = self._log_path.open("a", encoding="utf-8", buffering=1)
        values_path: Path | None = None
        try:
            self._enter("resolving", AppStatus.resolving, "准备 chart 与 values")
            values = dict(self._spec.values)
            self._apply_image(values)
            self._apply_node_port(values)
            if values:
                values_path = self._run_dir / "values.yaml"
                values_path.write_text(
                    yaml.safe_dump(values, allow_unicode=True, sort_keys=False),
                    encoding="utf-8",
                )
                values_path.chmod(0o600)

            self._enter("installing", AppStatus.installing, "执行 helm upgrade --install")
            await self._helm(values_path)
            self._enter("verifying", AppStatus.verifying, "验证 Pod 与访问地址")
            await self._verify_pods()
            verify_url = self._spec.verify_url
            if verify_url:
                await self._verify_url(verify_url)
            return AppResult(
                node_port=self._spec.node_port,
                verify_url=verify_url,
                chart=self._spec.chart,
            )
        finally:
            if values_path is not None:
                values_path.unlink(missing_ok=True)
            if self._log_handle is not None:
                self._log_handle.close()
                self._log_handle = None

    async def cancel(self) -> None:
        self._cancelled = True
        if self._commands is not None:
            await self._commands.cancel()

    # ------------------------------------------------------------------
    # 步骤
    # ------------------------------------------------------------------

    async def _helm(self, values_path: Path | None) -> None:
        argv = [
            "helm",
            "upgrade",
            "--install",
            self._spec.release_name,
            self._spec.chart,
            "--kubeconfig",
            self._kubeconfig,
            "--namespace",
            self._spec.namespace,
            "--create-namespace",
            "--wait",
            "--timeout",
            f"{int(self._settings.app_install_timeout_seconds)}s",
        ]
        if self._spec.repo_url:
            argv.extend(["--repo", self._spec.repo_url])
        if self._spec.chart_version:
            argv.extend(["--version", self._spec.chart_version])
        if values_path is not None:
            argv.extend(["--values", str(values_path)])
        result = await self._run_streaming(argv, phase="installing")
        if result.returncode != 0:
            text = (result.output or "").lower()
            code = (
                ErrorCode.CHART_PULL_FAILED
                if any(marker in text for marker in _PULL_MARKERS)
                else ErrorCode.APP_INSTALL_FAILED
            )
            raise AppError(
                code,
                "helm 安装失败",
                phase="installing",
                detail=result.output[-2000:],
            )

    async def _verify_pods(self) -> None:
        deadline = (
            asyncio.get_running_loop().time()
            + self._settings.app_install_timeout_seconds
        )
        last = ""
        while asyncio.get_running_loop().time() < deadline:
            if self._cancelled:
                raise AppCancelled(phase="verifying")
            pods = await self._pods()
            bad = [
                f"{item['name']}={item['phase']}"
                for item in pods
                if not item["ready"]
            ]
            current = f"pods={len(pods)} not_ready={','.join(bad)}"
            if current != last:
                self._log(f"verify: {current}")
                last = current
            if pods and not bad:
                return
            await asyncio.sleep(5)
        raise AppError(
            ErrorCode.APP_VERIFY_FAILED,
            "Pod 在超时时间内未全部 Ready",
            phase="verifying",
            detail=last,
        )

    async def _pods(self) -> list[dict[str, Any]]:
        selector = f"app.kubernetes.io/instance={self._spec.release_name}"
        payload = await self._kubectl_json(
            [
                "-n",
                self._spec.namespace,
                "get",
                "pods",
                "-l",
                selector,
                "-o",
                "json",
            ]
        )
        items = (payload or {}).get("items") or []
        if not items:
            payload = await self._kubectl_json(
                ["-n", self._spec.namespace, "get", "pods", "-o", "json"]
            )
            items = [
                item
                for item in (payload or {}).get("items") or []
                if str((item.get("metadata") or {}).get("name", "")).startswith(
                    self._spec.release_name
                )
            ]
        result: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            metadata = item.get("metadata") or {}
            status = item.get("status") or {}
            conditions = status.get("conditions") or []
            ready = any(
                condition.get("type") == "Ready"
                and _is_true(condition.get("status"))
                for condition in conditions
                if isinstance(condition, dict)
            )
            result.append(
                {
                    "name": metadata.get("name"),
                    "phase": status.get("phase"),
                    "ready": ready,
                }
            )
        return result

    async def _verify_url(self, url: str) -> None:
        deadline = asyncio.get_running_loop().time() + 120
        last_error = ""
        async with httpx.AsyncClient(follow_redirects=True, timeout=5.0) as client:
            while asyncio.get_running_loop().time() < deadline:
                if self._cancelled:
                    raise AppCancelled(phase="verifying")
                try:
                    response = await client.get(url)
                except httpx.HTTPError as exc:
                    last_error = str(exc)
                else:
                    if response.status_code == self._spec.verify_status:
                        self._log(f"verify url ok: {url} -> {response.status_code}")
                        return
                    last_error = f"HTTP {response.status_code}"
                self._log(f"verify url not ready: {url} {last_error}")
                await asyncio.sleep(5)
        raise AppError(
            ErrorCode.APP_VERIFY_FAILED,
            f"访问地址未返回预期状态码：{url}",
            phase="verifying",
            detail=last_error,
        )

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    def _apply_image(self, values: dict[str, Any]) -> None:
        if not self._spec.image:
            return
        repository, tag = _split_image(self._spec.image)
        image = values.setdefault("image", {})
        if isinstance(image, dict):
            image["repository"] = repository
            if tag:
                image["tag"] = tag
        global_values = values.setdefault("global", {})
        if isinstance(global_values, dict):
            security = global_values.setdefault("security", {})
            if isinstance(security, dict):
                security["allowInsecureImages"] = True

    def _apply_node_port(self, values: dict[str, Any]) -> None:
        if self._spec.node_port is None:
            return
        service = values.setdefault("service", {})
        if isinstance(service, dict):
            service["type"] = "NodePort"
            service["nodePort"] = self._spec.node_port

    async def _kubectl_json(self, argv: list[str]) -> dict[str, Any] | None:
        result = await self._run_capture(
            ["kubectl", "--kubeconfig", self._kubeconfig, *argv], phase="verifying"
        )
        if result.returncode != 0:
            return None
        try:
            payload = json.loads(result.output)
        except ValueError:
            return None
        return payload if isinstance(payload, dict) else None

    def _command(self) -> CommandRunner:
        if self._commands is None:
            self._commands = CommandRunner(cwd=self._run_dir, log=self._log)
        return self._commands

    async def _run_capture(self, argv: list[str], *, phase: str) -> CommandResult:
        try:
            return await self._command().run_capture(argv, timeout=60.0)
        except CommandCancelled as exc:
            raise AppCancelled(phase=phase) from exc
        except CommandTimeout as exc:
            raise AppError(
                ErrorCode.COMMAND_TIMEOUT, str(exc), phase=phase, detail=exc.output
            ) from exc
        except CommandError as exc:
            raise AppError(
                ErrorCode.COMMAND_NOT_FOUND, str(exc), phase=phase, detail=exc.output
            ) from exc

    async def _run_streaming(self, argv: list[str], *, phase: str) -> CommandResult:
        try:
            return await self._command().run_streaming(
                argv, timeout=self._settings.app_install_timeout_seconds + 60
            )
        except CommandCancelled as exc:
            raise AppCancelled(phase=phase) from exc
        except CommandTimeout as exc:
            raise AppError(
                ErrorCode.COMMAND_TIMEOUT, str(exc), phase=phase, detail=exc.output
            ) from exc
        except CommandError as exc:
            raise AppError(
                ErrorCode.COMMAND_NOT_FOUND, str(exc), phase=phase, detail=exc.output
            ) from exc

    def _enter(self, phase: str, status: AppStatus, message: str) -> None:
        self._log(f"== {message} ==")
        if self._on_progress is not None:
            self._on_progress(phase, status, message)

    def _log(self, message: str) -> None:
        if self._log_handle is not None:
            self._log_handle.write(message + "\n")


def _is_true(value: Any) -> bool:
    """kubectl 的 JSON 里 status 是字符串 ``"True"``，不是布尔。"""
    return value is True or (isinstance(value, str) and value.lower() == "true")


def _split_image(image: str) -> tuple[str, str | None]:
    if "@" in image:
        return image, None
    if ":" in image.rsplit("/", 1)[-1]:
        repository, tag = image.rsplit(":", 1)
        return repository, tag
    return image, None
