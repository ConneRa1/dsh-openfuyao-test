"""openFuyao 领域枚举：状态机常量、错误码与 CLI 退出码。

这里集中三件跨模块共用的“词汇”：

1. 状态机常量（哪些状态可发起/可取消/已终态）；
2. ``ErrorCode``——落库的 ``error_code``、REST 错误体、CLI 报错共用同一套枚举，
   避免字符串散落在 service/runner/CLI 三处各写一遍；
3. ``ExitCode``——CLI 的退出码契约，Agent 只靠它判成败（见模块底部说明）。

阶段 2/3 新增 Cluster/App 时，只在这里补状态集合与 ``build_plan`` 的阶段表，
不要把新的状态机常量写进各自的 service。
"""

from __future__ import annotations

from enum import IntEnum, StrEnum
from typing import Final

__all__ = [
    "ACTIVE_STATUSES",
    "BOOTSTRAP_ALLOWED_FROM",
    "BOOTSTRAP_PLAN",
    "CANCELLABLE_STATUSES",
    "PHASE_PROGRESS",
    "TERMINAL_STATUSES",
    "BootstrapPhase",
    "EnvironmentStatus",
    "ErrorCode",
    "ExitCode",
    "PlanStep",
    "build_plan",
    "is_terminal",
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


class ClusterStatus(StrEnum):
    """业务集群状态。``ready`` 是唯一目标态；``failed``/``cancelled`` 是终态。"""

    pending = "pending"
    preflight = "preflight"
    creating = "creating"
    joining = "joining"
    waiting_ready = "waiting_ready"
    ready = "ready"
    failed = "failed"
    cancelled = "cancelled"


class ClusterPhase(StrEnum):
    preflight = "preflight"
    render = "render"
    submitted = "submitted"
    control_plane = "control_plane"
    joining = "joining"
    wait_ready = "wait_ready"
    done = "done"


class NodeRole(StrEnum):
    master = "master"
    worker = "worker"


class NodeStatus(StrEnum):
    pending = "pending"
    bootstrapping = "bootstrapping"
    joined = "joined"
    ready = "ready"
    failed = "failed"


class AppStatus(StrEnum):
    pending = "pending"
    resolving = "resolving"
    installing = "installing"
    verifying = "verifying"
    deployed = "deployed"
    failed = "failed"
    cancelled = "cancelled"


#: 已经落定、不可再被取消覆盖的状态。
TERMINAL_STATUSES: Final = frozenset(
    {
        EnvironmentStatus.ready,
        EnvironmentStatus.failed,
        EnvironmentStatus.cancelled,
    }
)

#: 正在执行中的状态：服务重启后需要被标记为中断，前端也不能再显示“进行中”。
ACTIVE_STATUSES: Final = frozenset(
    {
        EnvironmentStatus.bootstrapping,
        EnvironmentStatus.waiting_console,
    }
)

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


class ErrorCode(StrEnum):
    """跨层共用的错误码。

    命名规则：``<域>_<原因>``；一旦落库就被前端与历史消息引用，**只增不改**。
    阶段 2/3 的集群/应用错误码已经预留（方案 §4.4），实现时直接用，不要再造字符串。
    """

    # ------------------------------------------------------------------
    # 请求/状态机（REST 层，带 HTTP 状态码）
    # ------------------------------------------------------------------
    AGENT_NOT_FOUND = "AGENT_NOT_FOUND"
    ENVIRONMENT_NOT_FOUND = "ENVIRONMENT_NOT_FOUND"
    HOST_ALREADY_CLAIMED = "HOST_ALREADY_CLAIMED"
    CONFIRM_REQUIRED = "CONFIRM_REQUIRED"
    ENVIRONMENT_ALREADY_READY = "ENVIRONMENT_ALREADY_READY"
    BOOTSTRAP_IN_PROGRESS = "BOOTSTRAP_IN_PROGRESS"
    ENVIRONMENT_NOT_CANCELLABLE = "ENVIRONMENT_NOT_CANCELLABLE"
    PREFLIGHT_FAILED = "PREFLIGHT_FAILED"

    # ------------------------------------------------------------------
    # Bootstrap 执行（落库成 environment.error_code）
    # ------------------------------------------------------------------
    BOOTSTRAP_CANCELLED = "BOOTSTRAP_CANCELLED"
    BOOTSTRAP_INTERRUPTED = "BOOTSTRAP_INTERRUPTED"
    BOOTSTRAP_INTERNAL_ERROR = "BOOTSTRAP_INTERNAL_ERROR"
    BKE_DOWNLOAD_FAILED = "BKE_DOWNLOAD_FAILED"
    BKE_CHECKSUM_MISMATCH = "BKE_CHECKSUM_MISMATCH"
    BKE_INSTALL_FAILED = "BKE_INSTALL_FAILED"
    BKE_NOT_AVAILABLE = "BKE_NOT_AVAILABLE"
    BKE_PREFLIGHT_FAILED = "BKE_PREFLIGHT_FAILED"
    BKE_INIT_FAILED = "BKE_INIT_FAILED"
    BKE_INIT_INCOMPLETE = "BKE_INIT_INCOMPLETE"
    CONSOLE_TIMEOUT = "CONSOLE_TIMEOUT"
    PODS_NOT_READY = "PODS_NOT_READY"

    # ------------------------------------------------------------------
    # 子进程（process.py 抛出，由各 runner 翻译成带 phase 的错误）
    # ------------------------------------------------------------------
    COMMAND_NOT_FOUND = "COMMAND_NOT_FOUND"
    COMMAND_TIMEOUT = "COMMAND_TIMEOUT"

    # ------------------------------------------------------------------
    # 阶段 2/3（方案 §4.4 预留，实现时直接引用）
    # ------------------------------------------------------------------
    HOSTNAME_INVALID = "HOSTNAME_INVALID"
    NODE_UNREACHABLE = "NODE_UNREACHABLE"
    MEMORY_INSUFFICIENT = "MEMORY_INSUFFICIENT"
    CLUSTER_CREATE_TIMEOUT = "CLUSTER_CREATE_TIMEOUT"
    CHART_PULL_FAILED = "CHART_PULL_FAILED"
    APP_VERIFY_FAILED = "APP_VERIFY_FAILED"
    CONFLICT_EXISTS = "CONFLICT_EXISTS"
    CANCELLED = "CANCELLED"

    # ------------------------------------------------------------------
    # 阶段 2：集群/节点（§11.5；只增不改）
    # ------------------------------------------------------------------
    CLUSTER_NOT_FOUND = "CLUSTER_NOT_FOUND"
    CLUSTER_IN_PROGRESS = "CLUSTER_IN_PROGRESS"
    CLUSTER_NOT_CANCELLABLE = "CLUSTER_NOT_CANCELLABLE"
    CLUSTER_CREATE_FAILED = "CLUSTER_CREATE_FAILED"
    CLUSTER_INTERRUPTED = "CLUSTER_INTERRUPTED"
    CLUSTER_NOT_READY = "CLUSTER_NOT_READY"
    NODE_CREDENTIAL_MISSING = "NODE_CREDENTIAL_MISSING"
    NODE_PRIVILEGE_MISSING = "NODE_PRIVILEGE_MISSING"
    NODE_CPU_INSUFFICIENT = "NODE_CPU_INSUFFICIENT"
    NODE_DISK_INSUFFICIENT = "NODE_DISK_INSUFFICIENT"
    NODE_ROLE_INVALID = "NODE_ROLE_INVALID"
    NODE_COUNT_MISMATCH = "NODE_COUNT_MISMATCH"
    NODE_NOT_READY = "NODE_NOT_READY"

    # ------------------------------------------------------------------
    # 阶段 3：应用
    # ------------------------------------------------------------------
    APP_NOT_FOUND = "APP_NOT_FOUND"
    APP_IN_PROGRESS = "APP_IN_PROGRESS"
    APP_INTERRUPTED = "APP_INTERRUPTED"
    APP_INSTALL_FAILED = "APP_INSTALL_FAILED"
    APP_CANCELLED = "APP_CANCELLED"

    # ------------------------------------------------------------------
    # CLI 自身（不发 HTTP、不落库）
    # ------------------------------------------------------------------
    API_UNREACHABLE = "API_UNREACHABLE"
    API_ERROR = "API_ERROR"
    TOKEN_REQUIRED = "TOKEN_REQUIRED"
    AGENT_ID_REQUIRED = "AGENT_ID_REQUIRED"
    WAIT_TIMEOUT = "WAIT_TIMEOUT"


class ExitCode(IntEnum):
    """CLI 退出码契约（Agent 靠它分流，不允许各命令自定义）。

    ====== ==========================================================
    0      成功；**包含幂等**：环境已 ready、Bootstrap 已在跑等“已是目标态”
    1      执行错误：参数缺失、API 不可达、业务错误（HTTP 4xx/5xx）
    2      需要确认：预检通过但未带 ``--confirm``，只打印影响面
    3      预检未通过：宿主机/节点门禁失败，未执行任何特权动作
    4      已到终态但不是目标态：``failed`` / ``cancelled``
    ====== ==========================================================
    """

    OK = 0
    ERROR = 1
    CONFIRM_REQUIRED = 2
    PREFLIGHT_FAILED = 3
    FAILED = 4


PHASE_PROGRESS: Final[dict[BootstrapPhase, int]] = {
    BootstrapPhase.preflight: 5,
    BootstrapPhase.install_bke: 20,
    BootstrapPhase.bke_init: 55,
    BootstrapPhase.wait_console: 90,
    BootstrapPhase.done: 100,
}


def progress_for_phase(
    phase: BootstrapPhase, mapping: dict[BootstrapPhase, int] | None = None
) -> int:
    """阶段 → 进度百分比。

    进度是**阶段映射**而不是真实完成度：真实进度无法从 CLI 输出可靠推断，猜出来的
    数字比“走到哪一步”更容易撒谎。阶段 2/3 传入自己的 ``mapping`` 即可复用。
    """
    return (mapping or PHASE_PROGRESS)[phase]


def is_terminal(status: str) -> bool:
    return status in TERMINAL_STATUSES


PlanStep = dict[str, str | int]


def build_plan(
    steps: tuple[tuple[str, str, int], ...],
) -> tuple[PlanStep, ...]:
    """把 ``(phase, title, progress)`` 三元组展开成给前端的执行计划。

    阶段 2/3 只要定义自己的三元组表就能复用同一份契约（``plan`` 字段）。
    """
    return tuple(
        {"phase": phase, "title": title, "progress": progress}
        for phase, title, progress in steps
    )


#: 创建 Environment 时返回给前端的执行计划（不含 bke 细节参数）。
BOOTSTRAP_PLAN: Final[tuple[PlanStep, ...]] = build_plan(
    (
        ("preflight", "环境预检", 5),
        ("install_bke", "安装 BKE", 20),
        ("bke_init", "初始化引导节点", 55),
        ("wait_console", "等待控制台就绪", 90),
    )
)


#: 业务集群执行计划（进度是阶段映射，不是真实完成度）。
CLUSTER_PLAN: Final[tuple[PlanStep, ...]] = build_plan(
    (
        ("preflight", "节点预检", 10),
        ("render", "渲染集群配置", 15),
        ("submitted", "提交创建", 30),
        ("control_plane", "启动控制面", 55),
        ("joining", "加入已有节点", 75),
        ("wait_ready", "等待节点就绪", 90),
        ("done", "完成", 100),
    )
)

CLUSTER_PROGRESS: Final[dict[ClusterPhase, int]] = {
    ClusterPhase.preflight: 10,
    ClusterPhase.render: 15,
    ClusterPhase.submitted: 30,
    ClusterPhase.control_plane: 55,
    ClusterPhase.joining: 75,
    ClusterPhase.wait_ready: 90,
    ClusterPhase.done: 100,
}

CLUSTER_TERMINAL_STATUSES: Final = frozenset(
    {ClusterStatus.ready, ClusterStatus.failed, ClusterStatus.cancelled}
)

CLUSTER_ACTIVE_STATUSES: Final = frozenset(
    {
        ClusterStatus.preflight,
        ClusterStatus.creating,
        ClusterStatus.joining,
        ClusterStatus.waiting_ready,
    }
)

CLUSTER_CANCELLABLE_STATUSES: Final = CLUSTER_ACTIVE_STATUSES

#: 允许再次发起创建的状态（ready 幂等返回，不重跑）。
CLUSTER_CREATE_ALLOWED_FROM: Final = frozenset(
    {
        ClusterStatus.pending,
        ClusterStatus.failed,
        ClusterStatus.cancelled,
    }
)

APP_TERMINAL_STATUSES: Final = frozenset(
    {AppStatus.deployed, AppStatus.failed, AppStatus.cancelled}
)
APP_ACTIVE_STATUSES: Final = frozenset(
    {AppStatus.resolving, AppStatus.installing, AppStatus.verifying}
)
APP_CANCELLABLE_STATUSES: Final = APP_ACTIVE_STATUSES
