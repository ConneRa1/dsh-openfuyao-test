"""openFuyao 宿主机快检（不依赖 bke）。

预检拆成两段：本模块只做**快检**，`bke preflight init` 由 Runner 在 BKE 安装后执行。
快检的原则是只读：不安装软件、不启停服务、不改网络，因此可以在 API 的创建环境
请求里直接执行，也允许用户反复重试。

所有检查结果都结构化为 ``PreflightCheck``：``fail`` 阻止继续，``warn`` 允许继续但
必须在 UI 明示（例如内存低于 16 GiB、NTP 未同步）。
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import socket
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

CheckStatus = Literal["pass", "warn", "fail"]

#: 必须可达的安装源（TCP 443 即可，不校验 HTTP 状态码）
NETWORK_ENDPOINTS: tuple[tuple[str, str, int], ...] = (
    ("BKE 下载源", "openfuyao.obs.cn-north-4.myhuaweicloud.com", 443),
    ("镜像仓库", "cr.openfuyao.cn", 443),
    ("应用市场", "charts.bitnami.com", 443),
)

#: BKE 初始化会占用的端口
REQUIRED_PORTS: tuple[int, ...] = (30010, 6443, 80, 443)

_RESIDUE_COMMANDS = ("docker", "k3s", "containerd")
_RESIDUE_PATHS = ("/var/lib/rancher", "/etc/rancher/k3s", "/var/lib/docker")

_MIB = 1024
_GIB = 1024**3


@dataclass(frozen=True, slots=True)
class HostFacts:
    """快检需要的宿主机事实；测试可直接构造，无需真的探测本机。"""

    host: str
    os_id: str
    os_version: str
    arch: str
    cpu_count: int
    mem_total_mb: int
    mem_available_mb: int
    disk_total_gb: float
    disk_free_gb: float
    is_root: bool
    has_tar: bool
    residues: tuple[str, ...]
    busy_ports: tuple[int, ...]
    unreachable_endpoints: tuple[str, ...]
    ntp_synced: bool | None


@dataclass(frozen=True, slots=True)
class PreflightCheck:
    code: str
    title: str
    status: CheckStatus
    message: str
    detail: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "title": self.title,
            "status": self.status,
            "message": self.message,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class PreflightReport:
    host: str
    checked_at: str
    checks: tuple[PreflightCheck, ...]

    @property
    def failed(self) -> tuple[PreflightCheck, ...]:
        return tuple(check for check in self.checks if check.status == "fail")

    @property
    def warnings(self) -> tuple[PreflightCheck, ...]:
        return tuple(check for check in self.checks if check.status == "warn")

    @property
    def ready(self) -> bool:
        return not self.failed

    def summary(self) -> dict[str, int]:
        return {
            "total": len(self.checks),
            "pass": sum(check.status == "pass" for check in self.checks),
            "warn": len(self.warnings),
            "fail": len(self.failed),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "checked_at": self.checked_at,
            "ready": self.ready,
            "summary": self.summary(),
            "checks": [check.to_dict() for check in self.checks],
        }


def detect_host_ip() -> str:
    """探测本机主 IP；UDP connect 不会发包，离线时回退到主机名解析。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            address = probe.getsockname()[0]
            if address and not address.startswith("127."):
                return str(address)
    except OSError:
        pass
    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return "127.0.0.1"


def _read_os_release(path: Path = Path("/etc/os-release")) -> tuple[str, str]:
    values: dict[str, str] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if not separator:
                continue
            values[key.strip()] = value.strip().strip("\"'")
    except OSError:
        logger.warning("Cannot read %s; OS checks will fail", path)
    return values.get("ID", "").lower(), values.get("VERSION_ID", "")


def _read_meminfo(path: Path = Path("/proc/meminfo")) -> tuple[int, int]:
    values: dict[str, int] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            key, _, rest = line.partition(":")
            parts = rest.split()
            if not parts:
                continue
            try:
                values[key] = int(parts[0])
            except ValueError:
                continue
    except OSError:
        return 0, 0
    # /proc/meminfo 的单位是 kB
    return values.get("MemTotal", 0) // _MIB, values.get("MemAvailable", 0) // _MIB


def _listening_ports() -> set[int] | None:
    """读取内核的 LISTEN 端口。

    非 root 时 bind 特权端口会得到 EACCES，用 bind 探测会把 80/443 误判为占用，
    因此优先读 /proc；只有读不到时才退回 bind。
    """
    ports: set[int] = set()
    for path in (Path("/proc/net/tcp"), Path("/proc/net/tcp6")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()[1:]
        except OSError:
            return None
        for line in lines:
            fields = line.split()
            if len(fields) < 4 or fields[3] != "0A":
                continue
            _, _, port_hex = fields[1].rpartition(":")
            try:
                ports.add(int(port_hex, 16))
            except ValueError:
                continue
    return ports


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", port))
        except OSError:
            return False
    return True


def _busy_ports() -> tuple[int, ...]:
    listening = _listening_ports()
    if listening is None:
        return tuple(port for port in REQUIRED_PORTS if not _port_is_free(port))
    return tuple(port for port in REQUIRED_PORTS if port in listening)


def _tcp_reachable(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _ntp_synced() -> bool | None:
    executable = shutil.which("timedatectl")
    if executable is None:
        return None
    try:
        result = subprocess.run(
            [executable, "show", "-p", "NTPSynchronized", "--value"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip().lower()
    if value in ("yes", "true", "1"):
        return True
    if value in ("no", "false", "0"):
        return False
    return None


def _has_privilege() -> bool:
    """root 直接通过；否则要求 witty-service 能免密以 root 执行 bke。"""
    if os.geteuid() == 0:
        return True
    executable = shutil.which("sudo")
    if executable is None:
        return False
    try:
        result = subprocess.run(
            [executable, "-n", "-l", "bke"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def collect_host_facts() -> HostFacts:
    os_id, os_version = _read_os_release()
    mem_total_mb, mem_available_mb = _read_meminfo()
    try:
        disk = shutil.disk_usage("/")
        disk_total_gb = round(disk.total / _GIB, 1)
        disk_free_gb = round(disk.free / _GIB, 1)
    except OSError:
        disk_total_gb = disk_free_gb = 0.0

    residues = [f"command:{name}" for name in _RESIDUE_COMMANDS if shutil.which(name)]
    residues.extend(f"path:{path}" for path in _RESIDUE_PATHS if Path(path).exists())
    busy_ports = _busy_ports()
    unreachable = tuple(
        label
        for label, host, port in NETWORK_ENDPOINTS
        if not _tcp_reachable(host, port)
    )
    return HostFacts(
        host=detect_host_ip(),
        os_id=os_id,
        os_version=os_version,
        arch=platform.machine(),
        cpu_count=os.cpu_count() or 0,
        mem_total_mb=mem_total_mb,
        mem_available_mb=mem_available_mb,
        disk_total_gb=disk_total_gb,
        disk_free_gb=disk_free_gb,
        is_root=_has_privilege(),
        has_tar=shutil.which("tar") is not None,
        residues=tuple(residues),
        busy_ports=busy_ports,
        unreachable_endpoints=unreachable,
        ntp_synced=_ntp_synced(),
    )


def _check(
    code: str,
    title: str,
    status: CheckStatus,
    message: str,
    **detail: Any,
) -> PreflightCheck:
    return PreflightCheck(
        code=code,
        title=title,
        status=status,
        message=message,
        detail=detail,
    )


def _evaluate_os(facts: HostFacts) -> PreflightCheck:
    if facts.os_id != "openeuler":
        return _check(
            "os",
            "操作系统",
            "fail",
            f"当前系统为 {facts.os_id or '未知'}，需要 openEuler",
            id=facts.os_id,
            version=facts.os_version,
        )
    if facts.os_version != "26.09":
        return _check(
            "os",
            "操作系统",
            "warn",
            f"当前 openEuler {facts.os_version}；MVP 基线为 26.09（快速入门基线 22.03）",
            id=facts.os_id,
            version=facts.os_version,
        )
    return _check(
        "os",
        "操作系统",
        "pass",
        "openEuler 26.09",
        id=facts.os_id,
        version=facts.os_version,
    )


def _evaluate_arch(facts: HostFacts) -> PreflightCheck:
    if facts.arch not in ("x86_64", "aarch64"):
        return _check(
            "arch",
            "CPU 架构",
            "fail",
            f"不支持的架构 {facts.arch}（仅 x86_64/aarch64）",
            arch=facts.arch,
        )
    return _check("arch", "CPU 架构", "pass", facts.arch, arch=facts.arch)


def _evaluate_cpu(facts: HostFacts) -> PreflightCheck:
    if facts.cpu_count < 8:
        return _check(
            "cpu",
            "CPU 核数",
            "fail",
            f"{facts.cpu_count} 核，低于 AIO 最低 8 核",
            cpu_count=facts.cpu_count,
        )
    return _check(
        "cpu",
        "CPU 核数",
        "pass",
        f"{facts.cpu_count} 核",
        cpu_count=facts.cpu_count,
    )


def _evaluate_memory(facts: HostFacts) -> PreflightCheck:
    total_gib = round(facts.mem_total_mb / _MIB, 1)
    available_gib = round(facts.mem_available_mb / _MIB, 1)
    detail = {
        "total_mb": facts.mem_total_mb,
        "available_mb": facts.mem_available_mb,
    }
    if facts.mem_total_mb < 14 * _MIB or facts.mem_available_mb < 2 * _MIB:
        return _check(
            "memory",
            "内存",
            "fail",
            f"总内存 {total_gib} GiB、可用 {available_gib} GiB，低于 AIO 最低要求",
            **detail,
        )
    if facts.mem_total_mb < 16 * _MIB:
        return _check(
            "memory",
            "内存",
            "warn",
            f"总内存 {total_gib} GiB，低于推荐 16 GiB；同机运行 PolyMind 需保留 2 GiB",
            **detail,
        )
    return _check(
        "memory",
        "内存",
        "pass",
        f"总内存 {total_gib} GiB，可用 {available_gib} GiB",
        **detail,
    )


def _evaluate_disk(facts: HostFacts) -> PreflightCheck:
    detail = {
        "total_gb": facts.disk_total_gb,
        "free_gb": facts.disk_free_gb,
    }
    if facts.disk_total_gb < 50 or facts.disk_free_gb < 20:
        return _check(
            "disk",
            "系统盘",
            "fail",
            f"总 {facts.disk_total_gb} GiB、可用 {facts.disk_free_gb} GiB，空间不足",
            **detail,
        )
    if facts.disk_total_gb < 100 or facts.disk_free_gb < 100:
        return _check(
            "disk",
            "系统盘",
            "warn",
            f"总 {facts.disk_total_gb} GiB、可用 {facts.disk_free_gb} GiB；建议可用 ≥100 GiB",
            **detail,
        )
    return _check(
        "disk",
        "系统盘",
        "pass",
        f"总 {facts.disk_total_gb} GiB、可用 {facts.disk_free_gb} GiB",
        **detail,
    )


def _evaluate_residue(facts: HostFacts) -> PreflightCheck:
    if facts.residues:
        return _check(
            "clean_host",
            "宿主机清洁度",
            "fail",
            "检测到 Docker/K8s 残留，bke init 可能因版本冲突失败",
            residues=list(facts.residues),
        )
    return _check(
        "clean_host",
        "宿主机清洁度",
        "pass",
        "未检测到 Docker/K8s 残留",
    )


def _evaluate_ports(facts: HostFacts) -> PreflightCheck:
    if facts.busy_ports:
        return _check(
            "ports",
            "端口占用",
            "fail",
            "以下端口已被占用：" + ", ".join(str(port) for port in facts.busy_ports),
            busy_ports=list(facts.busy_ports),
        )
    return _check(
        "ports",
        "端口占用",
        "pass",
        "30010/6443/80/443 均空闲",
    )


def _evaluate_network(facts: HostFacts) -> PreflightCheck:
    if facts.unreachable_endpoints:
        return _check(
            "network",
            "安装源连通性",
            "fail",
            "以下安装源不可达：" + "、".join(facts.unreachable_endpoints),
            unreachable=list(facts.unreachable_endpoints),
        )
    return _check(
        "network",
        "安装源连通性",
        "pass",
        "BKE 下载源、镜像仓库、应用市场均可达",
    )


def _evaluate_ntp(facts: HostFacts) -> PreflightCheck:
    if facts.ntp_synced is True:
        return _check("ntp", "NTP 校时", "pass", "系统时钟已同步")
    if facts.ntp_synced is False:
        return _check(
            "ntp",
            "NTP 校时",
            "warn",
            "系统时钟未同步；UDP/123 不可达时请设置 OPENFUYAO_ENABLE_NTP=false",
        )
    return _check(
        "ntp",
        "NTP 校时",
        "warn",
        "无法确认 NTP 同步状态；UDP/123 不可达时请设置 OPENFUYAO_ENABLE_NTP=false",
    )


def evaluate(facts: HostFacts) -> PreflightReport:
    """把宿主机事实映射为检查项（纯函数，便于单测覆盖门禁策略）。"""
    checks = (
        _evaluate_os(facts),
        _evaluate_arch(facts),
        _evaluate_cpu(facts),
        _evaluate_memory(facts),
        _evaluate_disk(facts),
        _check(
            "root",
            "执行权限",
            "pass" if facts.is_root else "fail",
            "root 权限可用" if facts.is_root else "需要 root 或可用的 sudo",
        ),
        _check(
            "tar",
            "tar 依赖",
            "pass" if facts.has_tar else "fail",
            "tar 已安装" if facts.has_tar else "缺少 tar，请执行 dnf install -y tar",
        ),
        _evaluate_residue(facts),
        _evaluate_ports(facts),
        _evaluate_network(facts),
        _evaluate_ntp(facts),
    )
    return PreflightReport(
        host=facts.host,
        checked_at=datetime.now(UTC).isoformat(),
        checks=checks,
    )


def run_preflight() -> PreflightReport:
    """采集本机事实并执行快检；只读，可重复调用。"""
    return evaluate(collect_host_facts())
