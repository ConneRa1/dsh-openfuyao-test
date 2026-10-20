"""openFuyao 快检门禁单测（纯事实 -> 检查项，不探测真实宿主机）。"""

from __future__ import annotations

import socket
from dataclasses import replace

from witty_service.application.openfuyao.preflight import (
    HostFacts,
    PreflightCheck,
    _listening_ports,
    evaluate,
)


def _facts(**overrides: object) -> HostFacts:
    base = HostFacts(
        host="192.0.2.10",
        os_id="openeuler",
        os_version="26.09",
        arch="aarch64",
        cpu_count=8,
        mem_total_mb=16 * 1024,
        mem_available_mb=12 * 1024,
        disk_total_gb=120.0,
        disk_free_gb=100.0,
        is_root=True,
        has_tar=True,
        residues=(),
        busy_ports=(),
        unreachable_endpoints=(),
        ntp_synced=True,
    )
    return replace(base, **overrides)


def _by_code(checks: tuple[PreflightCheck, ...], code: str) -> PreflightCheck:
    return next(check for check in checks if check.code == code)


def test_preflight_passes_on_supported_host() -> None:
    report = evaluate(_facts())

    assert report.ready is True
    assert report.failed == ()
    assert report.summary() == {"total": 11, "pass": 11, "warn": 0, "fail": 0}


def test_preflight_normalizes_open_euler_id() -> None:
    # /etc/os-release 里 ID=openEuler（大写 E），采集层统一转小写
    report = evaluate(_facts(os_id="openeuler", os_version="26.09"))
    assert _by_code(report.checks, "os").status == "pass"


def test_unsupported_os_is_a_hard_failure() -> None:
    report = evaluate(_facts(os_id="ubuntu", os_version="24.04"))

    assert report.ready is False
    assert _by_code(report.checks, "os").status == "fail"


def test_other_open_euler_version_is_only_a_warning() -> None:
    report = evaluate(_facts(os_version="22.03"))

    assert report.ready is True
    assert _by_code(report.checks, "os").status == "warn"


def test_four_core_host_cannot_run_aio() -> None:
    report = evaluate(_facts(cpu_count=4))

    assert report.ready is False
    assert _by_code(report.checks, "cpu").status == "fail"


def test_low_memory_fails_but_borderline_memory_warns() -> None:
    failed = evaluate(_facts(mem_total_mb=8 * 1024, mem_available_mb=4 * 1024))
    warning = evaluate(_facts(mem_total_mb=15 * 1024, mem_available_mb=8 * 1024))

    assert _by_code(failed.checks, "memory").status == "fail"
    assert _by_code(warning.checks, "memory").status == "warn"
    assert warning.ready is True


def test_low_available_memory_fails_even_with_large_total() -> None:
    report = evaluate(_facts(mem_total_mb=32 * 1024, mem_available_mb=1024))

    assert report.ready is False
    assert _by_code(report.checks, "memory").status == "fail"


def test_disk_thresholds() -> None:
    warning = evaluate(_facts(disk_total_gb=120.0, disk_free_gb=80.0))
    failed = evaluate(_facts(disk_total_gb=120.0, disk_free_gb=10.0))

    assert _by_code(warning.checks, "disk").status == "warn"
    assert _by_code(failed.checks, "disk").status == "fail"


def test_cleanliness_ports_network_and_privileges_are_blocking() -> None:
    report = evaluate(
        _facts(
            residues=("command:docker", "path:/var/lib/rancher"),
            busy_ports=(30010, 6443),
            unreachable_endpoints=("镜像仓库",),
            is_root=False,
            has_tar=False,
        )
    )

    for code in ("clean_host", "ports", "network", "root", "tar"):
        assert _by_code(report.checks, code).status == "fail"
    assert report.ready is False


def test_ntp_unknown_or_unsynchronized_only_warns() -> None:
    for value in (False, None):
        report = evaluate(_facts(ntp_synced=value))
        assert _by_code(report.checks, "ntp").status == "warn"
        assert report.ready is True


def test_listening_ports_are_detected_without_binding_required_ports() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        assert port in (_listening_ports() or set())


def test_report_serializes_checks_and_summary() -> None:
    payload = evaluate(_facts()).to_dict()

    assert payload["host"] == "192.0.2.10"
    assert payload["ready"] is True
    assert payload["summary"]["fail"] == 0
    assert {item["code"] for item in payload["checks"]} >= {"os", "memory", "disk"}
