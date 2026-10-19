"""openFuyao Environment 的领域枚举与状态机常量。"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

__all__ = [
    "BOOTSTRAP_ALLOWED_FROM",
    "BOOTSTRAP_PLAN",
    "CANCELLABLE_STATUSES",
    "PHASE_PROGRESS",
    "TERMINAL_STATUSES",
    "BootstrapPhase",
    "EnvironmentStatus",
    "progress_for_phase",
]


class EnvironmentStatus(StrEnum):
    pending = "pending"
    preflight = "preflight"
    bootstrapping = "bootstrapping"
    waiting_console = "waiting_console"
    ready = "ready"
    failed = "failed"
    cancelled = "cancelled"


class BootstrapPhase(StrEnum):
    preflight = "preflight"
    install_bke = "install_bke"
    bke_init = "bke_init"
    wait_console = "wait_console"
    done = "done"


#: 可以发起/重试 Bootstrap 的状态。ready 不允许重跑，避免误覆盖可用环境。
BOOTSTRAP_ALLOWED_FROM: Final = frozenset(
    {
        EnvironmentStatus.pending,
        EnvironmentStatus.preflight,
        EnvironmentStatus.failed,
        EnvironmentStatus.cancelled,
    }
)

CANCELLABLE_STATUSES: Final = frozenset(
    {
        EnvironmentStatus.preflight,
        EnvironmentStatus.bootstrapping,
        EnvironmentStatus.waiting_console,
    }
)

TERMINAL_STATUSES: Final = frozenset(
    {
        EnvironmentStatus.ready,
        EnvironmentStatus.failed,
        EnvironmentStatus.cancelled,
    }
)

PHASE_PROGRESS: Final[dict[BootstrapPhase, int]] = {
    BootstrapPhase.preflight: 5,
    BootstrapPhase.install_bke: 20,
    BootstrapPhase.bke_init: 55,
    BootstrapPhase.wait_console: 90,
    BootstrapPhase.done: 100,
}


def progress_for_phase(phase: BootstrapPhase) -> int:
    return PHASE_PROGRESS[phase]


#: 创建 Environment 时返回给前端的执行计划（不含 bke 细节参数）。
BOOTSTRAP_PLAN: Final[tuple[dict[str, str | int], ...]] = (
    {"phase": "preflight", "title": "环境预检", "progress": 5},
    {"phase": "install_bke", "title": "安装 BKE", "progress": 20},
    {"phase": "bke_init", "title": "初始化引导节点", "progress": 55},
    {"phase": "wait_console", "title": "等待控制台就绪", "progress": 90},
)
