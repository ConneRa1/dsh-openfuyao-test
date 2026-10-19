"""openFuyao 控制台信号识别（``openfuyao.open`` 事件载荷构建）。

openFuyao 部署完成后，agent 用 ``write`` 工具写出一个约定信号文件；本模块把该次
写入翻译成前端可消费的载荷，由 runtime 在写入成功后下发 ``openfuyao.open`` 事件，
驱动右侧面板自动打开并切换到对应管理面地址。

信号文件**不参与** ``artifact.*`` 产物（扩展名不在产物白名单内），只承担“面板开关”
这一语义；载荷契约与前端 ``parseOpenfuyaoOpen`` 对齐：
- ``{}`` —— 打开面板但不改地址（沿用当前/已持久化地址）；
- ``{"url": "<地址>"}`` —— 打开面板并切换到该地址。
"""

from __future__ import annotations

import json
from pathlib import PurePosixPath
from typing import Any

from witty_agent_server.runtimes.artifact_detector import (
    extract_write_arguments,
    pick_write_content,
    pick_write_path,
)

# 约定的信号文件名：agent 部署完成后用 write 工具写出，内容为 JSON。
OPENFUYAO_SIGNAL_FILENAME = "openfuyao-console.signal"


def is_openfuyao_signal_path(path_value: Any) -> bool:
    """路径的文件名是否命中 openFuyao 控制台信号约定（不看目录层级）。"""
    if not isinstance(path_value, str) or not path_value.strip():
        return False
    name = PurePosixPath(path_value.strip().replace("\\", "/")).name
    return name == OPENFUYAO_SIGNAL_FILENAME


def build_openfuyao_open_payload(args: Any) -> dict[str, Any] | None:
    """从 ``write`` 工具参数构建 ``openfuyao.open`` 载荷。

    非信号文件返回 ``None``（调用方应跳过）；是信号文件但内容缺失/非法 JSON 时回退为
    ``{}``（仍打开面板），避免一次内容笔误让面板彻底打不开。
    """
    raw = extract_write_arguments(args)
    if not is_openfuyao_signal_path(pick_write_path(raw)):
        return None

    content = pick_write_content(raw)
    if not isinstance(content, str) or not content.strip():
        return {}
    try:
        parsed = json.loads(content)
    except ValueError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    url = parsed.get("url")
    if isinstance(url, str) and url.strip():
        return {"url": url.strip()}
    return {}
