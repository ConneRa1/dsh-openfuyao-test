"""openFuyao 领域枚举契约：错误码、退出码、计划与进度映射。"""

from __future__ import annotations

import pytest

from witty_service.domain.openfuyao import (
    BOOTSTRAP_PLAN,
    BootstrapPhase,
    EnvironmentStatus,
    ErrorCode,
    ExitCode,
    build_plan,
    is_terminal,
    progress_for_phase,
)


def test_error_codes_are_unique_and_round_trip() -> None:
    values = [code.value for code in ErrorCode]

    assert len(values) == len(set(values))
    # 落库/回读走的是字符串，必须能从字符串反查回枚举
    assert ErrorCode("PREFLIGHT_FAILED") is ErrorCode.PREFLIGHT_FAILED


def test_stage_two_and_three_error_codes_are_reserved() -> None:
    """方案 §4.4 的错误码先落枚举，实现阶段 2/3 时直接引用，不再造字符串。"""
    required = {
        "HOSTNAME_INVALID",
        "NODE_UNREACHABLE",
        "MEMORY_INSUFFICIENT",
        "PREFLIGHT_FAILED",
        "CLUSTER_CREATE_TIMEOUT",
        "CHART_PULL_FAILED",
        "APP_VERIFY_FAILED",
        "CONFLICT_EXISTS",
        "CANCELLED",
    }

    assert required <= {code.value for code in ErrorCode}


def test_error_codes_compare_as_plain_strings() -> None:
    """历史数据与前端断言都按字符串比较，枚举必须保持 str 语义。"""
    assert ErrorCode.BKE_INIT_FAILED == "BKE_INIT_FAILED"
    assert f"{ErrorCode.BKE_INIT_FAILED}" == "BKE_INIT_FAILED"
    assert ErrorCode.BKE_INIT_FAILED in {"BKE_INIT_FAILED"}


def test_exit_code_contract() -> None:
    assert ExitCode.OK == 0
    assert ExitCode.ERROR == 1
    assert ExitCode.CONFIRM_REQUIRED == 2
    assert ExitCode.PREFLIGHT_FAILED == 3
    assert ExitCode.FAILED == 4
    # agent 用它做整数比较，必须能被 int() 接受
    assert int(ExitCode.PREFLIGHT_FAILED) == 3


def test_build_plan_keeps_phase_title_progress_shape() -> None:
    plan = build_plan((("resolve", "解析应用", 10), ("install", "安装", 60)))

    assert plan == (
        {"phase": "resolve", "title": "解析应用", "progress": 10},
        {"phase": "install", "title": "安装", "progress": 60},
    )
    assert BOOTSTRAP_PLAN[0]["phase"] == BootstrapPhase.preflight


def test_progress_for_phase_accepts_per_domain_mapping() -> None:
    custom = {BootstrapPhase.bke_init: 42}

    assert progress_for_phase(BootstrapPhase.bke_init) == 55
    assert progress_for_phase(BootstrapPhase.bke_init, custom) == 42


def test_progress_for_phase_rejects_unknown_phase_in_custom_mapping() -> None:
    with pytest.raises(KeyError):
        progress_for_phase(BootstrapPhase.preflight, {BootstrapPhase.done: 100})


def test_is_terminal_matches_status_sets() -> None:
    assert is_terminal("ready") is True
    assert is_terminal(EnvironmentStatus.failed) is True
    assert is_terminal("cancelled") is True
    assert is_terminal("bootstrapping") is False
    assert is_terminal("preflight") is False
