"""openFuyao Bootstrap 执行器：下载/校验 BKE、bke init、等待控制台。

进程独立成会话（``start_new_session=True``），取消时按进程组回收，避免留下
orphan ``bke``。stdout/stderr 合并落 ``<work_dir>/<env>/bootstrap.log``，API 的
``/logs`` 端点按字节游标读取该文件。

这里不做状态持久化：阶段回调交给 ``EnvironmentService``，Runner 只负责“执行 +
产出结果/异常”，因此可以脱离数据库单测。
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import os
import re
import signal
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from witty_service.application.openfuyao.console_health import (
    build_console_url,
    build_proxy_url,
    check_console,
)
from witty_service.application.openfuyao.preflight import (
    PreflightReport,
    run_preflight,
)
from witty_service.config import OpenFuyaoSettings
from witty_service.domain.openfuyao import BootstrapPhase, EnvironmentStatus, ErrorCode

logger = logging.getLogger(__name__)

COMPLETE_MARKER = "BKE initialization is complete"
_PROXY_SCHEME = "http"

ProgressCallback = Callable[[BootstrapPhase, EnvironmentStatus, str], None]


class BootstrapError(RuntimeError):
    """Bootstrap 失败；``code`` 直接落库给前端展示。"""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        phase: BootstrapPhase,
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.phase = phase
        self.detail = detail


class BootstrapCancelled(BootstrapError):
    def __init__(self, *, phase: BootstrapPhase) -> None:
        super().__init__(ErrorCode.BOOTSTRAP_CANCELLED, "Bootstrap 已取消", phase=phase)


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    console_url: str
    proxy_url: str
    bke_version: str | None
    os_version: str | None


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    output: str
    marker_seen: bool = False


class BootstrapRunner:
    def __init__(
        self,
        *,
        environment_id: str,
        host: str,
        settings: OpenFuyaoSettings,
        work_dir: Path,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        self._environment_id = environment_id
        self._host = host
        self._settings = settings
        self._work_dir = work_dir / environment_id
        self._on_progress = on_progress
        self._log_path = self._work_dir / "bootstrap.log"
        self._log_handle: Any = None
        self._process: asyncio.subprocess.Process | None = None
        self._cancel_event = asyncio.Event()
        self._cancelled = False
        self._phase = BootstrapPhase.preflight

    @property
    def log_path(self) -> Path:
        return self._log_path

    async def run(self, *, preflight: PreflightReport | None = None) -> BootstrapResult:
        self._work_dir.mkdir(parents=True, exist_ok=True)
        self._log_path.write_text("", encoding="utf-8")
        self._log_handle = self._log_path.open("a", encoding="utf-8", buffering=1)
        try:
            report = preflight or run_preflight()
            self._enter(BootstrapPhase.preflight, "环境预检")
            if not report.ready:
                failed = "；".join(
                    f"{check.title}: {check.message}" for check in report.failed
                )
                raise BootstrapError(
                    ErrorCode.PREFLIGHT_FAILED,
                    "宿主机预检未通过",
                    phase=BootstrapPhase.preflight,
                    detail=failed,
                )
            self._enter(BootstrapPhase.install_bke, "安装并校验 BKE")
            bke_version = await self._install_bke()
            self._enter(BootstrapPhase.bke_init, "初始化引导节点")
            await self._bke_init()
            self._enter(
                BootstrapPhase.wait_console,
                "等待控制台就绪",
                status=EnvironmentStatus.waiting_console,
            )
            await self._wait_console()
            await self._wait_pods()
            return BootstrapResult(
                console_url=build_console_url(self._host, self._settings.console_port),
                proxy_url=build_proxy_url(
                    self._host,
                    self._settings.proxy_port,
                    scheme=_PROXY_SCHEME,
                ),
                bke_version=bke_version,
                os_version=_os_version_from_report(report),
            )
        finally:
            if self._log_handle is not None:
                self._log_handle.close()
                self._log_handle = None

    async def cancel(self) -> None:
        self._cancelled = True
        self._cancel_event.set()
        await self._terminate_process()

    # ------------------------------------------------------------------
    # 执行步骤
    # ------------------------------------------------------------------

    async def _install_bke(self) -> str | None:
        script = await self._download_script()
        result = await self._run_streaming(
            ["bash", str(script)],
            timeout=600,
            phase=BootstrapPhase.install_bke,
        )
        if result.returncode != 0:
            raise BootstrapError(
                ErrorCode.BKE_INSTALL_FAILED,
                "BKE 安装脚本执行失败",
                phase=BootstrapPhase.install_bke,
                detail=result.output,
            )

        version = await self._run_capture(
            ["bke", "version"], timeout=30, phase=BootstrapPhase.install_bke
        )
        if version.returncode != 0:
            raise BootstrapError(
                ErrorCode.BKE_NOT_AVAILABLE,
                "BKE 安装后无法执行 bke version",
                phase=BootstrapPhase.install_bke,
                detail=version.output,
            )

        preflight = await self._run_streaming(
            [
                "bke",
                "preflight",
                "init",
                "--onlineImage",
                self._settings.bke_image,
                "--hostIP",
                self._host,
                "--confirm",
            ],
            timeout=300,
            phase=BootstrapPhase.install_bke,
        )
        if preflight.returncode != 0:
            if self._settings.allow_unsupported_os and _only_os_matrix_failure(
                preflight.output
            ):
                self._log(
                    "WARN: bke preflight 仅报告 OS/内核矩阵不匹配，"
                    "按 OPENFUYAO_ALLOW_UNSUPPORTED_OS 继续"
                )
            else:
                raise BootstrapError(
                    ErrorCode.BKE_PREFLIGHT_FAILED,
                    "bke preflight init 未通过",
                    phase=BootstrapPhase.install_bke,
                    detail=preflight.output,
                )
        bke_version = _parse_bke_version(version.output)
        if bke_version is None:
            self._log("WARN: 无法从 `bke version` 输出解析版本号，bke_version 留空")
        return bke_version

    async def _bke_init(self) -> None:
        argv = [
            "bke",
            "init",
            "--onlineImage",
            self._settings.bke_image,
            "--hostIP",
            self._host,
            "--installConsole=true",
            "--confirm",
        ]
        if not self._settings.enable_ntp:
            argv.insert(-1, "--enableNTP=false")
        result = await self._run_streaming(
            argv,
            timeout=self._settings.init_timeout_seconds,
            phase=BootstrapPhase.bke_init,
            marker=COMPLETE_MARKER,
        )
        if result.returncode != 0:
            raise BootstrapError(
                ErrorCode.BKE_INIT_FAILED,
                "bke init 执行失败",
                phase=BootstrapPhase.bke_init,
                detail=result.output,
            )
        if not result.marker_seen and COMPLETE_MARKER not in result.output:
            raise BootstrapError(
                ErrorCode.BKE_INIT_INCOMPLETE,
                "bke init 退出但未出现完成标记",
                phase=BootstrapPhase.bke_init,
                detail=result.output,
            )

    async def _wait_console(self) -> None:
        console_url = build_console_url(self._host, self._settings.console_port)
        deadline = (
            asyncio.get_running_loop().time() + self._settings.console_timeout_seconds
        )
        while asyncio.get_running_loop().time() < deadline:
            if self._cancelled:
                raise BootstrapCancelled(phase=BootstrapPhase.wait_console)
            health = await check_console(console_url, retries=1)
            if health.reachable:
                self._log(f"console reachable: {console_url} ({health.http_status})")
                return
            self._log(f"console not ready: {health.error}")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._cancel_event.wait(), timeout=5)
        raise BootstrapError(
            ErrorCode.CONSOLE_TIMEOUT,
            "控制台在超时时间内未就绪",
            phase=BootstrapPhase.wait_console,
            detail=console_url,
        )

    async def _wait_pods(self) -> None:
        deadline = asyncio.get_running_loop().time() + 60
        last_output = ""
        while asyncio.get_running_loop().time() < deadline:
            if self._cancelled:
                raise BootstrapCancelled(phase=BootstrapPhase.wait_console)
            result = await self._run_capture(
                ["kubectl", "get", "pods", "-A", "--no-headers"],
                timeout=20,
                phase=BootstrapPhase.wait_console,
            )
            last_output = result.output
            if result.returncode == 0:
                bad = _not_ready_pods(result.output)
                if not bad:
                    self._log("all pods are Running/Completed")
                    return
                self._log("pods not ready: " + ", ".join(bad[:5]))
            else:
                self._log(
                    f"kubectl get pods failed: {_first_line(result.output) or '无输出'}"
                )
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._cancel_event.wait(), timeout=5)
        raise BootstrapError(
            ErrorCode.PODS_NOT_READY,
            "引导集群 Pod 未全部就绪",
            phase=BootstrapPhase.wait_console,
            detail=last_output,
        )

    # ------------------------------------------------------------------
    # 下载与子进程
    # ------------------------------------------------------------------

    async def _download_script(self) -> Path:
        url = self._settings.bke_download_url
        self._log(f"downloading {url}")
        async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
            try:
                response = await client.get(url)
                response.raise_for_status()
                checksum_response = await client.get(url + ".sha256")
                checksum_response.raise_for_status()
            except httpx.HTTPError as exc:
                raise BootstrapError(
                    ErrorCode.BKE_DOWNLOAD_FAILED,
                    "BKE 下载脚本或校验和不可达",
                    phase=BootstrapPhase.install_bke,
                    detail=str(exc),
                ) from exc

        payload = response.content
        expected = checksum_response.text.strip().split()[0].lower()
        actual = hashlib.sha256(payload).hexdigest()
        if not expected or actual != expected:
            raise BootstrapError(
                ErrorCode.BKE_CHECKSUM_MISMATCH,
                "BKE 下载脚本校验和不匹配",
                phase=BootstrapPhase.install_bke,
                detail=f"expected={expected} actual={actual}",
            )

        script = self._work_dir / "download.sh"
        script.write_bytes(payload)
        script.chmod(0o700)
        (self._work_dir / "download.sh.sha256").write_text(
            checksum_response.text, encoding="utf-8"
        )
        self._log(f"checksum verified: {actual}")
        return script

    def _subprocess_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["KUBECONFIG"] = self._settings.kubeconfig
        return env

    def _privileged(self, argv: list[str]) -> list[str]:
        """安装脚本与 bke 需要 root；后端以 witty-service 运行时经 sudo 提权。"""
        if os.geteuid() == 0:
            return argv
        return ["sudo", "-n", *argv]

    async def _run_streaming(
        self,
        argv: list[str],
        *,
        timeout: float,
        phase: BootstrapPhase,
        marker: str | None = None,
    ) -> CommandResult:
        self._phase = phase
        self._require_not_cancelled(phase)
        self._work_dir.mkdir(parents=True, exist_ok=True)
        argv = self._privileged(argv)
        self._log(f"$ {' '.join(argv)}")
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(self._work_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
                env=self._subprocess_env(),
            )
        except FileNotFoundError as exc:
            raise BootstrapError(
                ErrorCode.COMMAND_NOT_FOUND,
                f"命令不存在：{argv[0]}",
                phase=phase,
                detail=str(exc),
            ) from exc
        self._process = process
        tail: deque[str] = deque(maxlen=200)
        saw_marker = False

        async def _pump() -> None:
            nonlocal saw_marker
            assert process.stdout is not None
            while True:
                raw = await process.stdout.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").rstrip()
                if not line:
                    continue
                tail.append(line)
                self._log(line)
                if marker and marker in line:
                    saw_marker = True

        try:
            await asyncio.wait_for(_pump(), timeout=timeout)
            returncode = await process.wait()
        except TimeoutError:
            await self._terminate_process()
            raise BootstrapError(
                ErrorCode.COMMAND_TIMEOUT,
                f"{Path(argv[0]).name} 执行超时（{int(timeout)}s）",
                phase=phase,
                detail="\n".join(tail),
            ) from None
        finally:
            if self._process is process:
                self._process = None

        if self._cancelled:
            raise BootstrapCancelled(phase=phase)
        return CommandResult(
            returncode=returncode,
            output="\n".join(tail),
            marker_seen=saw_marker,
        )

    async def _run_capture(
        self, argv: list[str], *, timeout: float, phase: BootstrapPhase
    ) -> CommandResult:
        self._phase = phase
        self._require_not_cancelled(phase)
        self._work_dir.mkdir(parents=True, exist_ok=True)
        argv = self._privileged(argv)
        self._log(f"$ {' '.join(argv)}")
        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(self._work_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
                env=self._subprocess_env(),
            )
        except FileNotFoundError as exc:
            raise BootstrapError(
                ErrorCode.COMMAND_NOT_FOUND,
                f"命令不存在：{argv[0]}",
                phase=phase,
                detail=str(exc),
            ) from exc
        self._process = process
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
            returncode = process.returncode or 0
        except TimeoutError:
            await self._terminate_process()
            raise BootstrapError(
                ErrorCode.COMMAND_TIMEOUT,
                f"{Path(argv[0]).name} 执行超时（{int(timeout)}s）",
                phase=phase,
            ) from None
        finally:
            if self._process is process:
                self._process = None
        if self._cancelled:
            raise BootstrapCancelled(phase=phase)
        output = stdout.decode("utf-8", errors="replace").strip()
        if output:
            self._log(output)
        return CommandResult(returncode=returncode, output=output)

    async def _terminate_process(self) -> None:
        process = self._process
        if process is None or process.returncode is not None:
            return
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except ProcessLookupError:
                return
            await process.wait()

    def _require_not_cancelled(self, phase: BootstrapPhase) -> None:
        if self._cancelled:
            raise BootstrapCancelled(phase=phase)

    def _enter(
        self,
        phase: BootstrapPhase,
        message: str,
        *,
        status: EnvironmentStatus = EnvironmentStatus.bootstrapping,
    ) -> None:
        self._phase = phase
        self._log(f"== {message} ==")
        if self._on_progress is not None:
            self._on_progress(phase, status, message)

    def _log(self, message: str) -> None:
        if self._log_handle is None:
            return
        self._log_handle.write(message + "\n")


def _first_line(text: str) -> str | None:
    for line in text.splitlines():
        if line.strip():
            return line.strip()[:64]
    return None


_VERSION_FIELD = re.compile(r"^\s*version\s*:\s*(\S+)\s*$", re.IGNORECASE)
_SEMVER = re.compile(r"\bv?(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.]+)?)\b")


def _parse_bke_version(output: str) -> str | None:
    """从 ``bke version`` 输出里取版本号，取不到就返回 ``None``。

    ``bke`` 会先把 ologger 的 JSON 日志写到 stdout（首行形如
    ``{"time":...,"level":"INFO","msg":"ologger config not found..."}``），
    所以**不能取第一行**：线上库里的 ``bke_version`` 曾是半截日志。
    这里先跳过 JSON 行，优先读 ``version: <值>`` 字段，其次找非日志行里的语义化版本。
    """
    text_lines = [
        line.strip()
        for line in output.splitlines()
        if line.strip() and not line.strip().startswith("{")
    ]
    for line in text_lines:
        match = _VERSION_FIELD.match(line)
        if match:
            return match.group(1)[:64]
    for line in text_lines:
        match = _SEMVER.search(line)
        if match:
            return match.group(1)[:64]
    return None


def _os_version_from_report(report: PreflightReport) -> str | None:
    for check in report.checks:
        if check.code == "os":
            value = check.detail.get("version")
            return str(value) if value else None
    return None


def _only_os_matrix_failure(output: str) -> bool:
    """判断 preflight 失败是否只有“发行版/内核矩阵”两项（26.09 已知例外）。"""
    failed_rows = [
        line for line in output.splitlines() if "│" in line and "失败" in line
    ]
    if len(failed_rows) != 2:
        return False
    return any("主机发行版" in line for line in failed_rows) and any(
        "内核兼容性" in line for line in failed_rows
    )


def _not_ready_pods(output: str) -> list[str]:
    bad: list[str] = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        status = parts[3]
        if status not in ("Running", "Completed"):
            bad.append(f"{parts[0]}/{parts[1]}={status}")
    return bad
