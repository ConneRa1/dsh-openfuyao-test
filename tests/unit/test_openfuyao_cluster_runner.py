"""阶段 2 预检 JSON → 错误码映射（不跑 bke）。"""

from __future__ import annotations

from witty_service.application.openfuyao.cluster_runner import (
    PreflightFailure,
    PreflightOutcome,
    _parse_preflight_json,
    failed_results,
    map_preflight_failure,
)
from witty_service.domain.openfuyao import ErrorCode

_NODE_MAP = {"bke-multi-n1": "192.0.2.11"}


def _result(rule: str, subject: str, actual_value: object) -> dict[str, object]:
    return {
        "ruleID": rule,
        "subject": subject,
        "status": "fail",
        "name": "检查",
        "actual": {"type": "bytes", "value": actual_value},
        "evidence": [{"kind": "probe", "observed": "observed detail"}],
        "remediation": "扩容后重试",
    }


def test_memory_failure_maps_to_node_and_code() -> None:
    failure = map_preflight_failure(
        _result("CLUSTER-RES-MEMORY", "bke-multi-n1", 3011952640),
        node_by_name=_NODE_MAP,
    )
    assert failure.code is ErrorCode.MEMORY_INSUFFICIENT
    assert failure.node_ip == "192.0.2.11"
    assert "扩容后重试" in failure.summary
    assert failure.to_dict()["rule_id"] == "CLUSTER-RES-MEMORY"


def test_unknown_rule_falls_back_to_preflight_failed() -> None:
    failure = map_preflight_failure(
        _result("CLUSTER-SOMETHING-NEW", "cluster", True), node_by_name={}
    )
    assert failure.code is ErrorCode.PREFLIGHT_FAILED
    assert failure.node_ip is None


def test_preflight_outcome_ready_except_tolerated() -> None:
    tolerated = PreflightFailure(
        rule_id="CLUSTER-PLAT-DISTRO",
        subject="bke-multi-m1",
        status="fail",
        node_ip="192.0.2.10",
        code=ErrorCode.PREFLIGHT_FAILED,
        message="distro",
        remediation="",
    )
    fatal = PreflightFailure(
        rule_id="CLUSTER-RES-MEMORY",
        subject="bke-multi-n1",
        status="fail",
        node_ip="192.0.2.11",
        code=ErrorCode.MEMORY_INSUFFICIENT,
        message="memory",
        remediation="",
    )
    outcome = PreflightOutcome(
        payload={}, failures=(tolerated, fatal), tolerated=(tolerated,)
    )
    assert not outcome.ready
    assert "memory" in outcome.summary()
    only_tolerated = PreflightOutcome(
        payload={}, failures=(tolerated,), tolerated=(tolerated,)
    )
    assert only_tolerated.ready
    assert "通过" in only_tolerated.summary()
    assert "未通过" not in only_tolerated.summary()


def test_failed_results_is_case_insensitive() -> None:
    """BKE 的 status 是大写 PASS/FAIL；只按小写匹配会让“预检永远通过”。"""
    payload = {
        "results": [
            {"ruleID": "CLUSTER-RES-MEMORY", "subject": "n1", "status": "FAIL"},
            {"ruleID": "CLUSTER-RES-CPU", "subject": "n1", "status": "PASS"},
        ]
    }
    failures = failed_results(payload)
    assert [item["ruleID"] for item in failures] == ["CLUSTER-RES-MEMORY"]


def test_parse_preflight_json_tolerates_progress_prefix() -> None:
    raw = 'level=INFO step=1\n{"overall": "PASS", "results": []}\n'
    payload = _parse_preflight_json(raw)
    assert payload is not None
    assert payload["overall"] == "PASS"
    assert _parse_preflight_json("not json") is None
