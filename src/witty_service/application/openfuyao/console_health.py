"""openFuyao 控制台健康检查。

控制台是自签 TLS，且登录入口会 302 到 OAuth；因此只要求 TCP/HTTP 有响应，
2xx/3xx 均视为可达。证书校验关闭是 MVP 的已知取舍：探针只访问 127.0.0.1/本机 IP，
不对外发起请求。
"""

from __future__ import annotations

import asyncio
import logging
import secrets
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


def console_user_url(console_url: str) -> str:
    return console_url.rstrip("/") + "/rest/auth/user"


@dataclass(frozen=True, slots=True)
class ConsoleSessionProbe:
    """控制台对 `sessionID` Cookie 的处理能力。

    这个探针只能**证明** Cookie 被 console-service 读到了（``True``），不能反证
    Cookie 被入口丢掉：老版本 bke-console-service 对任意随机 ``sessionID`` 都回
    ``cookie not found``，和完全没带 Cookie 的响应一模一样。因此无法区分时返回
    ``None``（未知），不再武断地给出 ``False`` —— 否则会把一个正常的引导节点控制台
    误判成“登录态存不住”，进而把两个控制台错误地合并成一个。
    """

    console_url: str
    reachable: bool
    session_capable: bool | None
    http_status: int | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.console_url,
            "reachable": self.reachable,
            "session_capable": self.session_capable,
            "reason": self.reason,
        }


def _console_probe_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("msg") or payload.get("message") or "")


async def probe_console_session(
    console_url: str,
    *,
    timeout: float = 3.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ConsoleSessionProbe:
    """探测控制台入口是否把 ``sessionID`` Cookie 交给 console-service。

    做法是对同一个 ``/rest/auth/user`` 发两次请求：一次带随机 ``sessionID``，一次不带。
    两次响应不同 ⇒ Cookie 确实进入了服务端的会话处理分支；两次完全一样 ⇒ 无法判断
    （入口丢 Cookie、或老版本 console-service 对未知会话固定回 ``cookie not found``）。

    不能只用“带 Cookie 的响应是 cookie not found”来判定入口丢 Cookie：老版本
    bke-console-service 即使收到 Cookie 也这么回。历史上正是这个误判把引导节点控制台
    自动回落成了业务控制台，导致两个 tab 显示同一个控制台。

    探针只发随机值，不创建会话，也不会触发账号锁定。
    """
    endpoint = console_user_url(console_url)
    probe_value = f"polymind-probe-{secrets.token_hex(12)}"
    try:
        async with httpx.AsyncClient(
            verify=False,
            timeout=timeout,
            follow_redirects=False,
            transport=transport,
        ) as client:
            seeded = await client.get(
                endpoint, headers={"Cookie": f"sessionID={probe_value}"}
            )
            try:
                anonymous = await client.get(endpoint)
            except httpx.HTTPError:
                anonymous = None
    except httpx.HTTPError as exc:
        return ConsoleSessionProbe(
            console_url=console_url,
            reachable=False,
            session_capable=None,
            reason=f"{type(exc).__name__}",
        )

    status = seeded.status_code
    message = _console_probe_message(seeded)
    lowered = message.lower()
    anonymous_signature = None
    if anonymous is not None:
        anonymous_signature = (
            anonymous.status_code,
            _console_probe_message(anonymous).lower(),
        )
    seeded_signature = (status, lowered)

    if status == 200:
        return ConsoleSessionProbe(
            console_url=console_url,
            reachable=True,
            session_capable=True,
            http_status=status,
            reason="probe_accepted",
        )
    if status == 401:
        if "cookie not found" in lowered:
            # 老 console-service 的固定回复：只有和匿名请求不同时才能证明 Cookie 被读到。
            if (
                anonymous_signature is not None
                and anonymous_signature != seeded_signature
            ):
                return ConsoleSessionProbe(
                    console_url=console_url,
                    reachable=True,
                    session_capable=True,
                    http_status=status,
                    reason="session_cookie_observed",
                )
            return ConsoleSessionProbe(
                console_url=console_url,
                reachable=True,
                session_capable=None,
                http_status=status,
                reason="session_cookie_unobservable",
            )
        if "sessionid" in lowered or "token" in lowered or "session" in lowered:
            return ConsoleSessionProbe(
                console_url=console_url,
                reachable=True,
                session_capable=True,
                http_status=status,
                reason="cookie_forwarded",
            )
        if anonymous_signature is not None and anonymous_signature != seeded_signature:
            return ConsoleSessionProbe(
                console_url=console_url,
                reachable=True,
                session_capable=True,
                http_status=status,
                reason="session_cookie_observed",
            )
        return ConsoleSessionProbe(
            console_url=console_url,
            reachable=True,
            session_capable=None,
            http_status=status,
            reason=message or "unauthorized",
        )
    return ConsoleSessionProbe(
        console_url=console_url,
        reachable=True,
        session_capable=None,
        http_status=status,
        reason=f"http_{status}",
    )


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
