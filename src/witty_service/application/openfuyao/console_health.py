"""openFuyao 控制台健康检查。

控制台是自签 TLS，且登录入口会 302 到 OAuth；因此只要求 TCP/HTTP 有响应，
2xx/3xx 均视为可达。证书校验关闭是 MVP 的已知取舍：探针只访问 127.0.0.1/本机 IP，
不对外发起请求。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ConsoleHealth:
    reachable: bool
    console_url: str
    http_status: int | None
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "console_reachable": self.reachable,
            "http_status": self.http_status,
            "console_url": self.console_url,
            "error": self.error,
        }


def console_login_url(console_url: str) -> str:
    return console_url.rstrip("/") + "/rest/auth/login"


def build_console_url(host: str, port: int) -> str:
    return f"https://{host}:{port}"


def build_proxy_url(host: str, port: int, *, scheme: str = "http") -> str:
    return f"{scheme}://{host}:{port}/"


async def check_console(
    console_url: str,
    *,
    timeout: float = 5.0,
    retries: int = 3,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ConsoleHealth:
    """GET 登录入口；2xx/3xx 视为可达。重试只针对网络错误/5xx。"""
    endpoint = console_login_url(console_url)
    last_error: str | None = None
    last_status: int | None = None
    async with httpx.AsyncClient(
        verify=False,
        timeout=timeout,
        follow_redirects=False,
        transport=transport,
    ) as client:
        for attempt in range(max(1, retries)):
            try:
                response = await client.get(endpoint)
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                last_status = response.status_code
                if 200 <= response.status_code < 400:
                    return ConsoleHealth(
                        reachable=True,
                        console_url=console_url,
                        http_status=response.status_code,
                        error=None,
                    )
                last_error = f"HTTP {response.status_code}"
                if response.status_code < 500:
                    break
            if attempt + 1 < retries:
                await asyncio.sleep(0.2)
    logger.info("Console health check failed: %s (%s)", endpoint, last_error)
    return ConsoleHealth(
        reachable=False,
        console_url=console_url,
        http_status=last_status,
        error=last_error,
    )
