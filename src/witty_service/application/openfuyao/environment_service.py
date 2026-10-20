"""openFuyao Environment 编排服务：创建、预检、Bootstrap、取消、日志。"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from witty_service.application.openfuyao.bootstrap_runner import (
    BootstrapCancelled,
    BootstrapError,
    BootstrapResult,
    BootstrapRunner,
)
from witty_service.application.openfuyao.console_health import (
    ConsoleHealth,
    build_console_url,
    build_proxy_url,
    check_console,
)
from witty_service.application.openfuyao.log_tail import (
    DEFAULT_CHUNK_BYTES,
    LogPage,
    read_log_page,
)
from witty_service.application.openfuyao.preflight import (
    PreflightReport,
    detect_host_ip,
    run_preflight,
)
from witty_service.config import OpenFuyaoSettings
from witty_service.domain.errors import DomainError
from witty_service.domain.openfuyao import (
    BOOTSTRAP_ALLOWED_FROM,
    BOOTSTRAP_PLAN,
    CANCELLABLE_STATUSES,
    BootstrapPhase,
    EnvironmentStatus,
    ErrorCode,
    is_terminal,
    progress_for_phase,
)
from witty_service.persistence.openfuyao_repository import (
    HostAlreadyClaimedError,
    OpenFuyaoEnvironmentRecord,
    OpenFuyaoRepository,
)

logger = logging.getLogger(__name__)


class AgentLookup(Protocol):
    def get_agent(self, agent_id: str) -> Any | None: ...


class RunnerFactory(Protocol):
    def __call__(
        self,
        *,
        environment_id: str,
        host: str,
        settings: OpenFuyaoSettings,
        work_dir: Path,
        on_progress: Callable[[BootstrapPhase, EnvironmentStatus, str], None],
    ) -> BootstrapRunner: ...


@dataclass(frozen=True, slots=True)
class CreateResult:
    environment: OpenFuyaoEnvironmentRecord | None
    preflight: PreflightReport
    plan: tuple[dict[str, str | int], ...]
    created: bool


def _now() -> datetime:
    return datetime.now(UTC)


def _not_found(environment_id: str) -> DomainError:
    return DomainError(
        code=ErrorCode.ENVIRONMENT_NOT_FOUND,
        message="openFuyao 环境不存在",
        status_code=404,
        details={"environment_id": environment_id},
    )


def _host_claimed(host: str) -> DomainError:
    return DomainError(
        code=ErrorCode.HOST_ALREADY_CLAIMED,
        message="该宿主机已被其他 Agent 的 openFuyao 环境占用",
        status_code=409,
        details={"host": host},
    )


class EnvironmentService:
    def __init__(
        self,
        *,
        repository: OpenFuyaoRepository,
        agent_repository: AgentLookup,
        settings: OpenFuyaoSettings,
        workspace_root: Path,
        runner_factory: RunnerFactory = BootstrapRunner,
        preflight_runner: Callable[[], PreflightReport] = run_preflight,
    ) -> None:
        self._repository = repository
        self._agent_repository = agent_repository
        self._settings = settings
        self._work_dir = (
            Path(settings.work_dir)
            if settings.work_dir
            else (workspace_root / "openfuyao")
        )
        self._runner_factory = runner_factory
        self._preflight_runner = preflight_runner
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._runners: dict[str, BootstrapRunner] = {}

    # ------------------------------------------------------------------
    # 查询 / 创建
    # ------------------------------------------------------------------

    def list_environments(
        self, *, agent_id: str | None = None
    ) -> list[OpenFuyaoEnvironmentRecord]:
        return self._repository.list(agent_id=agent_id)

    def get_environment(
        self, environment_id: str, *, agent_id: str | None = None
    ) -> OpenFuyaoEnvironmentRecord:
        record = self._repository.get(environment_id)
        if record is None or (agent_id is not None and record.agent_id != agent_id):
            raise _not_found(environment_id)
        return record

    async def create_environment(
        self, *, agent_id: str, dry_run: bool = False
    ) -> CreateResult:
        if self._agent_repository.get_agent(agent_id) is None:
            raise DomainError(
                code=ErrorCode.AGENT_NOT_FOUND,
                message="Agent 不存在",
                status_code=404,
                details={"agent_id": agent_id},
            )

        host = self._settings.host or detect_host_ip()
        report = await asyncio.to_thread(self._preflight_runner)
        existing = self._repository.get_by_host(host)
        if existing is not None:
            if existing.agent_id != agent_id:
                raise _host_claimed(host)
            if not dry_run and existing.status in (
                EnvironmentStatus.failed,
                EnvironmentStatus.cancelled,
            ):
                existing = self._repository.update(
                    existing.id,
                    status=(
                        EnvironmentStatus.preflight
                        if report.ready
                        else EnvironmentStatus.failed
                    ),
                    phase=BootstrapPhase.preflight,
                    progress=5 if report.ready else 0,
                    preflight_json=report.to_dict(),
                    os_version=_os_version(report),
                    error_code=None if report.ready else ErrorCode.PREFLIGHT_FAILED,
                    error_message=None if report.ready else _preflight_message(report),
                    finished_at=None if report.ready else _now(),
                )
            return CreateResult(
                environment=existing,
                preflight=report,
                plan=BOOTSTRAP_PLAN,
                created=False,
            )

        if dry_run:
            return CreateResult(
                environment=None,
                preflight=report,
                plan=BOOTSTRAP_PLAN,
                created=False,
            )

        record = self._create_record(agent_id=agent_id, host=host, report=report)
        return CreateResult(
            environment=record,
            preflight=report,
            plan=BOOTSTRAP_PLAN,
            created=True,
        )

    def _create_record(
        self, *, agent_id: str, host: str, report: PreflightReport
    ) -> OpenFuyaoEnvironmentRecord:
        ready = report.ready
        try:
            return self._repository.create(
                agent_id=agent_id,
                host=host,
                status=(
                    EnvironmentStatus.preflight if ready else EnvironmentStatus.failed
                ),
                phase=BootstrapPhase.preflight,
                progress=5 if ready else 0,
                preflight_json=report.to_dict(),
                os_version=_os_version(report),
                console_url=build_console_url(host, self._settings.console_port),
                proxy_url=build_proxy_url(
                    host,
                    self._settings.proxy_port,
                    scheme=self._settings.proxy_scheme,
                ),
                error_code=None if ready else ErrorCode.PREFLIGHT_FAILED,
                error_message=None if ready else _preflight_message(report),
            )
        except HostAlreadyClaimedError as exc:
            existing = self._repository.get_by_host(host)
            if existing is not None and existing.agent_id != agent_id:
                raise _host_claimed(host) from exc
            if existing is None:
                raise
            return existing

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------

    async def bootstrap(
        self, environment_id: str, *, confirm: bool
    ) -> OpenFuyaoEnvironmentRecord:
        if not confirm:
            raise DomainError(
                code=ErrorCode.CONFIRM_REQUIRED,
                message="Bootstrap 为破坏性操作，需要 confirm=true",
                status_code=400,
            )
        record = self.get_environment(environment_id)
        if record.status == EnvironmentStatus.ready:
            raise DomainError(
                code=ErrorCode.ENVIRONMENT_ALREADY_READY,
                message="环境已就绪，无需重复部署",
                status_code=409,
                details={"status": record.status},
            )
        if record.status not in BOOTSTRAP_ALLOWED_FROM:
            raise DomainError(
                code=ErrorCode.BOOTSTRAP_IN_PROGRESS,
                message="该环境正在部署或不可部署",
                status_code=409,
                details={"status": record.status},
            )

        report = await asyncio.to_thread(self._preflight_runner)
        if not report.ready:
            self._repository.update(
                environment_id,
                status=EnvironmentStatus.failed,
                phase=BootstrapPhase.preflight,
                progress=0,
                preflight_json=report.to_dict(),
                error_code=ErrorCode.PREFLIGHT_FAILED,
                error_message=_preflight_message(report),
                finished_at=_now(),
            )
            raise DomainError(
                code=ErrorCode.PREFLIGHT_FAILED,
                message="宿主机预检未通过，请修复后重试",
                status_code=400,
                details={"preflight": report.to_dict()},
            )

        if not self._repository.try_start_bootstrap(
            environment_id, allowed_statuses=BOOTSTRAP_ALLOWED_FROM
        ):
            current = self._repository.get(environment_id)
            raise DomainError(
                code=ErrorCode.BOOTSTRAP_IN_PROGRESS,
                message="该环境已有 Bootstrap 在执行",
                status_code=409,
                details={"status": current.status if current else None},
            )

        self._repository.update(
            environment_id,
            preflight_json=report.to_dict(),
            os_version=_os_version(report),
        )
        runner = self._runner_factory(
            environment_id=environment_id,
            host=record.host,
            settings=self._settings,
            work_dir=self._work_dir,
            on_progress=lambda phase, status, _message: self._apply_progress(
                environment_id, phase, status
            ),
        )
        self._runners[environment_id] = runner
        task = asyncio.create_task(self._run_bootstrap(environment_id, runner, report))
        self._tasks[environment_id] = task
        task.add_done_callback(lambda _task: self._tasks.pop(environment_id, None))
        return self.get_environment(environment_id)

    async def _run_bootstrap(
        self,
        environment_id: str,
        runner: BootstrapRunner,
        report: PreflightReport,
    ) -> None:
        try:
            result = await runner.run(preflight=report)
        except BootstrapCancelled as exc:
            self._repository.update(
                environment_id,
                status=EnvironmentStatus.cancelled,
                phase=exc.phase,
                error_code=exc.code,
                error_message=exc.message,
                finished_at=_now(),
            )
        except BootstrapError as exc:
            logger.warning(
                "openFuyao bootstrap failed: env=%s code=%s detail=%s",
                environment_id,
                exc.code,
                exc.detail,
            )
            self._repository.update(
                environment_id,
                status=EnvironmentStatus.failed,
                phase=exc.phase,
                error_code=exc.code,
                error_message=exc.message,
                finished_at=_now(),
            )
        except Exception:
            logger.exception("openFuyao bootstrap crashed: env=%s", environment_id)
            self._repository.update(
                environment_id,
                status=EnvironmentStatus.failed,
                phase=BootstrapPhase.bke_init,
                error_code=ErrorCode.BOOTSTRAP_INTERNAL_ERROR,
                error_message="Bootstrap 内部错误，请查看服务日志",
                finished_at=_now(),
            )
        else:
            self._mark_ready(environment_id, result)
        finally:
            self._runners.pop(environment_id, None)

    def _mark_ready(self, environment_id: str, result: BootstrapResult) -> None:
        record = self._repository.get(environment_id)
        proxy_url = result.proxy_url
        if record is not None:
            proxy_url = build_proxy_url(
                record.host,
                self._settings.proxy_port,
                scheme=self._settings.proxy_scheme,
            )
        self._repository.update(
            environment_id,
            status=EnvironmentStatus.ready,
            phase=BootstrapPhase.done,
            progress=100,
            console_url=result.console_url,
            proxy_url=proxy_url,
            bke_version=result.bke_version,
            os_version=result.os_version,
            error_code=None,
            error_message=None,
            finished_at=_now(),
        )

    def _apply_progress(
        self,
        environment_id: str,
        phase: BootstrapPhase,
        status: EnvironmentStatus,
    ) -> None:
        self._repository.update(
            environment_id,
            status=status,
            phase=phase,
            progress=progress_for_phase(phase),
        )

    async def cancel(self, environment_id: str) -> OpenFuyaoEnvironmentRecord:
        record = self.get_environment(environment_id)
        if record.status not in CANCELLABLE_STATUSES:
            raise DomainError(
                code=ErrorCode.ENVIRONMENT_NOT_CANCELLABLE,
                message="该环境当前不可取消",
                status_code=409,
                details={"status": record.status},
            )
        runner = self._runners.get(environment_id)
        if runner is not None:
            await runner.cancel()
        task = self._tasks.get(environment_id)
        if task is not None:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(asyncio.shield(task), timeout=10)
        current = self._repository.get(environment_id)
        if current is not None and is_terminal(current.status):
            # 取消与完成竞态：已经落定的终态（含 cancelled 自身）不被覆盖。
            return current
        return self._repository.update(
            environment_id,
            status=EnvironmentStatus.cancelled,
            error_code=ErrorCode.BOOTSTRAP_CANCELLED,
            error_message="Bootstrap 已取消",
            finished_at=_now(),
        ) or self.get_environment(environment_id)

    async def health(self, environment_id: str) -> ConsoleHealth:
        record = self.get_environment(environment_id)
        console_url = record.console_url or build_console_url(
            record.host, self._settings.console_port
        )
        return await check_console(console_url)

    # ------------------------------------------------------------------
    # 日志 / 恢复 / 关闭
    # ------------------------------------------------------------------

    def read_logs(
        self,
        environment_id: str,
        *,
        cursor: int = 0,
        limit_bytes: int = DEFAULT_CHUNK_BYTES,
    ) -> LogPage:
        self.get_environment(environment_id)
        return read_log_page(
            self.log_path(environment_id), cursor=cursor, limit_bytes=limit_bytes
        )

    def log_path(self, environment_id: str) -> Path:
        """日志落盘位置；与 Runner 的 ``<work_dir>/<env>/bootstrap.log`` 对齐。"""
        return self._work_dir / environment_id / "bootstrap.log"

    def recover_stale(self) -> int:
        return self._repository.recover_interrupted()

    async def close(self) -> None:
        for runner in list(self._runners.values()):
            with contextlib.suppress(Exception):
                await runner.cancel()
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks.clear()
        self._runners.clear()


def _os_version(report: PreflightReport) -> str | None:
    for check in report.checks:
        if check.code == "os":
            value = check.detail.get("version")
            return str(value) if value else None
    return None


def _preflight_message(report: PreflightReport) -> str:
    failures = [f"{check.title}: {check.message}" for check in report.failed]
    return "；".join(failures)[:500] or "预检未通过"
