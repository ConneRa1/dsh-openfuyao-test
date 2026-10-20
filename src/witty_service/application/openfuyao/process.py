"""受控子进程执行：流式/捕获两种模式、超时、进程组回收、sudo 提权。

Runner 只负责“跑什么命令、结果怎么解释”，进程生命周期全部在这里，避免阶段 2/3
的 runner 再各复制一份 ``start_new_session`` / ``killpg`` / 超时 / 日志泵逻辑。

三个不变量：

1. **独立会话**：所有子进程 ``start_new_session=True``，取消时按**进程组**回收。
   ``bke`` 会 fork k3s/containerd，只杀父进程会留孤儿继续占端口、继续写
   ``/etc/kubernetes``，下一次重试就撞“宿主不干净”；
2. **日志即现场**：输出逐行回调给 ``log``（落盘 + 进度），同时保留最后
   ``TAIL_LINES`` 行放进异常，失败时不需要再去看文件；
3. **失败可翻译**：异常只表达“命令层失败”（找不到/超时/取消），带 ``code`` 与
   ``output``；由各 runner 翻译成带 ``phase`` 的业务错误。
"""

from __future__ import annotations

import asyncio
import os
import signal
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from witty_service.domain.openfuyao import ErrorCode

__all__ = [
    "CommandCancelled",
    "CommandError",
    "CommandNotAvailable",
    "CommandResult",
    "CommandRunner",
    "CommandTimeout",
    "privileged",
]

#: 失败时保留的输出行数；够定位（一般最后几行才是根因）又不至于把错误体撑爆。
TAIL_LINES = 200

#: 取消时 SIGTERM 到 SIGKILL 的宽限
_TERM_GRACE_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    output: str
    #: 流式模式下是否看到调用方给的完成标记（``bke init`` 的完成行）
    marker_seen: bool = False


class CommandError(RuntimeError):
    """命令层失败；``code`` 供上层直接落库或再包一层。"""

    code: ErrorCode = ErrorCode.COMMAND_TIMEOUT

    def __init__(
        self,
        argv: Sequence[str],
        message: str,
        *,
        output: str | None = None,
        code: ErrorCode | None = None,
    ) -> None:
        super().__init__(message)
        self.argv = list(argv)
        self.output = output or ""
        if code is not None:
            self.code = code


class CommandNotAvailable(CommandError):
    def __init__(self, argv: Sequence[str]) -> None:
        super().__init__(
            argv,
            f"命令不存在：{argv[0] if argv else ''}",
            code=ErrorCode.COMMAND_NOT_FOUND,
        )


class CommandTimeout(CommandError):
    def __init__(
        self, argv: Sequence[str], timeout: float, *, output: str | None = None
    ) -> None:
        super().__init__(
            argv,
            f"{Path(argv[0]).name} 执行超时（{timeout:g}s）",
            output=output,
            code=ErrorCode.COMMAND_TIMEOUT,
        )
        self.timeout = timeout


class CommandCancelled(CommandError):
    def __init__(self, argv: Sequence[str], *, output: str | None = None) -> None:
        super().__init__(argv, "命令已取消", output=output, code=ErrorCode.CANCELLED)


def privileged(argv: Sequence[str]) -> list[str]:
    """需要 root 的命令在此统一提权。

    后端以 ``witty-service`` 服务用户运行，权限来自 sudoers 白名单；``-n``（非交互）
    保证拿不到免密时**立即失败**，不会卡在密码提示上把 API 进程挂死。
    """
    if os.geteuid() == 0:
        return list(argv)
    return ["sudo", "-n", *argv]


class CommandRunner:
    """一个工作目录 + 一份日志回调，负责把命令跑完并给出结果。"""

    def __init__(
        self,
        *,
        cwd: Path,
        log: Callable[[str], None],
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._cwd = cwd
        self._log = log
        self._env = dict(env) if env is not None else None
        self._process: asyncio.subprocess.Process | None = None
        self._cancelled = False

    # ------------------------------------------------------------------
    # 对外的两种模式
    # ------------------------------------------------------------------

    async def run_streaming(
        self,
        argv: Sequence[str],
        *,
        timeout: float,
        marker: str | None = None,
    ) -> CommandResult:
        """逐行泵输出（长任务、需要进度/完成标记时用）。"""
        self._require_not_cancelled(argv)
        process = await self._spawn(argv)
        self._process = process
        tail: deque[str] = deque(maxlen=TAIL_LINES)
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
            await self._kill()
            raise CommandTimeout(argv, timeout, output="\n".join(tail)) from None
        except asyncio.CancelledError:
            # 外层任务被取消（服务关闭）：先收进程组再让取消继续传播
            await self._kill()
            raise
        finally:
            if self._process is process:
                self._process = None

        if self._cancelled:
            raise CommandCancelled(argv, output="\n".join(tail))
        return CommandResult(
            returncode=returncode,
            output="\n".join(tail),
            marker_seen=saw_marker,
        )

    async def run_capture(
        self, argv: Sequence[str], *, timeout: float
    ) -> CommandResult:
        """一次读完输出（短命令、需要解析结果时用）。"""
        self._require_not_cancelled(argv)
        process = await self._spawn(argv)
        self._process = process
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except TimeoutError:
            await self._kill()
            raise CommandTimeout(argv, timeout) from None
        except asyncio.CancelledError:
            await self._kill()
            raise
        finally:
            if self._process is process:
                self._process = None

        if self._cancelled:
            raise CommandCancelled(argv)
        output = stdout.decode("utf-8", errors="replace").strip()
        if output:
            self._log(output)
        return CommandResult(returncode=process.returncode or 0, output=output)

    # ------------------------------------------------------------------
    # 取消
    # ------------------------------------------------------------------

    async def cancel(self) -> None:
        """标记取消并回收当前进程组；在途的 ``run_*`` 会抛 ``CommandCancelled``。"""
        self._cancelled = True
        await self._kill()

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _require_not_cancelled(self, argv: Sequence[str]) -> None:
        if self._cancelled:
            raise CommandCancelled(argv)

    async def _spawn(self, argv: Sequence[str]) -> asyncio.subprocess.Process:
        resolved = privileged(argv)
        self._log(f"$ {' '.join(resolved)}")
        self._cwd.mkdir(parents=True, exist_ok=True)
        try:
            return await asyncio.create_subprocess_exec(
                *resolved,
                cwd=str(self._cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
                env=dict(self._env) if self._env is not None else None,
            )
        except FileNotFoundError as exc:
            raise CommandNotAvailable(resolved) from exc

    async def _kill(self) -> None:
        process = self._process
        if process is None or process.returncode is not None:
            return
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(process.wait(), timeout=_TERM_GRACE_SECONDS)
            return
        except TimeoutError:
            pass
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except ProcessLookupError:
            return
        await process.wait()
