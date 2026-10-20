"""openFuyao 快速入门：Bootstrap 编排与面板数据。

只自动化快速入门阶段 1（预检 + 安装 BKE + bke init + 控制台就绪），
阶段 2/3 仍由用户在官方控制台手动完成。
"""

from __future__ import annotations

__all__ = ["Gate", "PreflightReport", "run_preflight"]

from witty_service.application.openfuyao.preflight import (
    Gate,
    PreflightReport,
    run_preflight,
)
