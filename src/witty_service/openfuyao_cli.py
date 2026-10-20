"""openFuyao 运维 CLI（``witty-service openfuyao ...``）。

- ``preflight``：只读宿主机门禁，不依赖后端；
- ``deploy/status/cancel/logs``：通过本机 REST API 驱动编排，Agent 不需要拼 ``bke``。

Agent 侧约定：``WITTY_AGENT_ID`` 由沙箱注入，``AUTH_TOKEN`` 从服务进程环境继承；
两个变量都缺失时用显式参数覆盖。

**退出码契约**（见 ``domain.openfuyao.ExitCode``，Agent 只靠它分流）::

    0  成功；包含幂等：环境已 ready、Bootstrap 已在跑等“已是目标态”
    1  执行错误：参数缺失、API 不可达、业务错误
    2  需要确认：预检通过但未带 --confirm
    3  预检未通过：门禁失败，未执行任何特权动作
    4  已到终态但不是目标态：failed / cancelled

``--json`` 时 stdout **只有一个 JSON 文档**，进度行（每阶段一行的人类可读输出）
一律不打印，避免 Agent 需要“取最后一段 JSON”。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from collections.abc import Sequence
from typing import Any

import httpx

from witty_service.application.openfuyao.preflight import (
    Gate,
    PreflightCheck,
    PreflightReport,
    run_preflight,
)
from witty_service.domain.openfuyao import (
    ACTIVE_STATUSES,
    EnvironmentStatus,
    ErrorCode,
    ExitCode,
    is_terminal,
)

_STATUS_MARK = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}
_DEFAULT_TIMEOUT = 900.0


class _ApiError(RuntimeError):
    def __init__(
        self, status: int, code: str, message: str, details: Any = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.details = details


def _print_preflight(report: PreflightReport) -> None:
    summary = report.summary()
    print(f"openFuyao 快检  host={report.host}  time={report.checked_at}")
    print("-" * 72)
    for check in report.checks:
        print(f"[{_STATUS_MARK[check.status]:4}] {check.title:<12} {check.message}")
    print("-" * 72)
    verdict = "通过" if report.ready else "未通过"
    print(
        f"结论：{verdict}（pass={summary['pass']} warn={summary['warn']} "
        f"fail={summary['fail']}）"
    )
    if report.ready and report.warnings:
        print("注意：存在警告项，继续前请确认影响面。")


def _print_environment(environment: dict[str, Any]) -> None:
    print(
        "环境 {id}  status={status} phase={phase} progress={progress}%".format(
            **environment
        )
    )
    if environment.get("console_url"):
        print(f"  console: {environment['console_url']}")
    if environment.get("proxy_url"):
        print(f"  proxy:   {environment['proxy_url']}")
    if environment.get("error_code"):
        print(
            f"  error:   {environment['error_code']} "
            f"{environment.get('error_message') or ''}"
        )


def _print_plan(plan: Sequence[dict[str, Any]]) -> None:
    if not plan:
        return
    print("")
    print("计划：")
    for step in plan:
        print(f"  {step['progress']:>3}%  {step['title']}")


class _Client:
    def __init__(self, base_url: str, token: str) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=30.0,
            headers={"Authorization": f"Bearer {token}"},
        )

    def close(self) -> None:
        self._client.close()

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise _ApiError(0, ErrorCode.API_UNREACHABLE, str(exc)) from exc
        if response.status_code >= 400:
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            error = payload.get("error") if isinstance(payload, dict) else None
            if isinstance(error, dict):
                raise _ApiError(
                    response.status_code,
                    str(error.get("code") or ErrorCode.API_ERROR),
                    str(error.get("message") or response.text),
                    error.get("details"),
                )
            raise _ApiError(response.status_code, ErrorCode.API_ERROR, response.text)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def create_environment(self, agent_id: str, *, dry_run: bool) -> dict[str, Any]:
        return self.request(
            "POST",
            "/openfuyao/environments",
            json={"agent_id": agent_id, "dry_run": dry_run},
        )

    def bootstrap(self, environment_id: str) -> dict[str, Any]:
        return self.request(
            "POST",
            f"/openfuyao/environments/{environment_id}/bootstrap",
            json={"confirm": True},
        )

    def cancel(self, environment_id: str) -> dict[str, Any]:
        return self.request("POST", f"/openfuyao/environments/{environment_id}/cancel")

    def list(self, agent_id: str) -> list[dict[str, Any]]:
        return self.request(
            "GET", "/openfuyao/environments", params={"agent_id": agent_id}
        )

    def get(self, environment_id: str) -> dict[str, Any]:
        return self.request("GET", f"/openfuyao/environments/{environment_id}")

    def logs(self, environment_id: str, cursor: int) -> dict[str, Any]:
        return self.request(
            "GET",
            f"/openfuyao/environments/{environment_id}/logs",
            params={"cursor": cursor},
        )


def _api_base_url(args: argparse.Namespace) -> str:
    from witty_service.config import get_settings

    return (
        args.api_url
        or os.getenv("OPENFUYAO_API_BASE_URL")
        or get_settings().openfuyao.api_base_url
    )


def _token(args: argparse.Namespace) -> str:
    from witty_service.config import get_settings

    token = args.token or os.getenv("AUTH_TOKEN") or get_settings().auth_token
    if not token:
        raise _ApiError(0, ErrorCode.TOKEN_REQUIRED, "缺少 AUTH_TOKEN/--token")
    return token


def _agent_id(args: argparse.Namespace) -> str:
    agent_id = args.agent_id or os.getenv("WITTY_AGENT_ID")
    if not agent_id:
        raise _ApiError(
            0,
            ErrorCode.AGENT_ID_REQUIRED,
            "缺少 WITTY_AGENT_ID/--agent-id（Agent 沙箱会自动注入前者）",
        )
    return agent_id


def _client(args: argparse.Namespace) -> _Client:
    return _Client(_api_base_url(args), _token(args))


def _latest_environment(client: _Client, args: argparse.Namespace) -> dict[str, Any]:
    if getattr(args, "environment_id", None):
        return client.get(args.environment_id)
    environments = client.list(_agent_id(args))
    if not environments:
        raise _ApiError(
            404, ErrorCode.ENVIRONMENT_NOT_FOUND, "该 Agent 还没有 openFuyao 环境"
        )
    return environments[0]


def _poll(
    client: _Client,
    environment: dict[str, Any],
    *,
    timeout: float,
    interval: float,
    quiet: bool = False,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    current = environment
    previous: tuple[str, str] | None = None
    while True:
        signature = (current["status"], current["phase"])
        if signature != previous:
            if not quiet:
                _print_environment(current)
            previous = signature
        if is_terminal(current["status"]):
            return current
        if time.monotonic() >= deadline:
            raise _ApiError(0, ErrorCode.WAIT_TIMEOUT, f"等待超过 {int(timeout)}s")
        time.sleep(interval)
        current = client.get(current["id"])


def _terminal_exit(environment: dict[str, Any]) -> ExitCode:
    """终态非 ready 才算失败；还在执行中（如 status 的 preflight）仍是 0。"""
    status = environment["status"]
    if status == EnvironmentStatus.ready:
        return ExitCode.OK
    if is_terminal(status):
        return ExitCode.FAILED
    return ExitCode.OK


def _finish(
    args: argparse.Namespace,
    *,
    exit_code: ExitCode,
    summary: str,
    environment: dict[str, Any] | None,
    preflight: dict[str, Any],
    plan: Sequence[dict[str, Any]],
    needs_confirm: bool = False,
) -> int:
    """统一收尾：``--json`` 只输出一个文档，否则打印预检、计划与结论。"""
    if args.json:
        print(
            json.dumps(
                {
                    "exit_code": int(exit_code),
                    "needs_confirm": needs_confirm,
                    "summary": summary,
                    "environment": environment,
                    "preflight": preflight,
                    "plan": list(plan),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return int(exit_code)

    _print_preflight(_report_from_dict(preflight))
    _print_plan(plan)
    print("")
    print(summary)
    if environment is not None:
        _print_environment(environment)
    return int(exit_code)


def _cmd_preflight(args: argparse.Namespace) -> int:
    report = run_preflight(Gate(args.gate))
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        _print_preflight(report)
    return int(ExitCode.OK if report.ready else ExitCode.PREFLIGHT_FAILED)


def _cmd_deploy(args: argparse.Namespace) -> int:
    client = _client(args)
    try:
        result = client.create_environment(_agent_id(args), dry_run=args.dry_run)
        preflight = result["preflight"]
        plan = result.get("plan") or []
        environment = result.get("environment")

        def finish(
            exit_code: ExitCode,
            summary: str,
            env: dict[str, Any] | None = environment,
            *,
            needs_confirm: bool = False,
        ) -> int:
            return _finish(
                args,
                exit_code=exit_code,
                summary=summary,
                environment=env,
                preflight=preflight,
                plan=plan,
                needs_confirm=needs_confirm,
            )

        if not preflight.get("ready"):
            return finish(
                ExitCode.PREFLIGHT_FAILED,
                "预检未通过，未执行任何特权动作；按上面列出的失败项逐项修复后重试。",
            )
        if environment is None:
            return finish(ExitCode.OK, "dry-run：未创建环境。")

        status = environment["status"]
        # 幂等：已 ready 不重复部署，直接给出地址（方案 §4.2）
        if status == EnvironmentStatus.ready:
            proxy = environment.get("proxy_url") or ""
            return finish(
                ExitCode.OK,
                f"环境已就绪，无需重复部署。{('代理地址：' + proxy) if proxy else ''}",
            )
        # 已在执行：不重复启动，跟随现有进度（重复执行同一条命令必须成功）
        if status in ACTIVE_STATUSES:
            current = environment
            if args.wait:
                current = _poll(
                    client,
                    environment,
                    timeout=args.timeout,
                    interval=args.interval,
                    quiet=args.json,
                )
                if current["status"] == EnvironmentStatus.ready:
                    return finish(
                        ExitCode.OK,
                        f"部署完成，代理地址：{current.get('proxy_url') or ''}",
                        current,
                    )
                return finish(
                    ExitCode.FAILED,
                    f"部署未成功结束：{current['status']}",
                    current,
                )
            return finish(
                ExitCode.OK,
                "Bootstrap 已在执行中，未重复启动；用 "
                "`witty-service openfuyao status --wait` 跟踪。",
            )

        if not args.confirm:
            return finish(
                ExitCode.CONFIRM_REQUIRED,
                "预检通过；加 --confirm 才会执行破坏性的 bke init。",
                needs_confirm=True,
            )

        started = client.bootstrap(environment["id"])
        if not args.wait:
            return finish(
                ExitCode.OK,
                "Bootstrap 已在后台启动；用 `witty-service openfuyao status "
                f"--environment-id {environment['id']} --wait` 跟踪。",
                started,
            )
        current = _poll(
            client,
            started,
            timeout=args.timeout,
            interval=args.interval,
            quiet=args.json,
        )
        if current["status"] == EnvironmentStatus.ready:
            return finish(
                ExitCode.OK,
                f"部署完成，代理地址：{current.get('proxy_url') or ''}",
                current,
            )
        return finish(
            ExitCode.FAILED,
            f"部署未成功结束：{current['status']}"
            f"{('（' + current['error_code'] + '）') if current.get('error_code') else ''}",
            current,
        )
    finally:
        client.close()


def _cmd_status(args: argparse.Namespace) -> int:
    client = _client(args)
    try:
        environment = _latest_environment(client, args)
        if args.wait:
            environment = _poll(
                client,
                environment,
                timeout=args.timeout,
                interval=args.interval,
                quiet=args.json,
            )
        if args.json:
            print(json.dumps(environment, ensure_ascii=False, indent=2))
        else:
            _print_environment(environment)
        return int(_terminal_exit(environment))
    finally:
        client.close()


def _cmd_cancel(args: argparse.Namespace) -> int:
    client = _client(args)
    try:
        environment = _latest_environment(client, args)
        cancelled = client.cancel(environment["id"])
        if args.json:
            print(json.dumps(cancelled, ensure_ascii=False, indent=2))
        else:
            _print_environment(cancelled)
        return int(ExitCode.OK)
    finally:
        client.close()


def _cmd_logs(args: argparse.Namespace) -> int:
    client = _client(args)
    try:
        environment = _latest_environment(client, args)
        cursor = args.cursor
        while True:
            page = client.logs(environment["id"], cursor)
            for line in page["lines"]:
                print(line)
            cursor = page["next_cursor"]
            if not args.follow or page["eof"]:
                return int(ExitCode.OK)
            environment = client.get(environment["id"])
            if is_terminal(environment["status"]):
                page = client.logs(environment["id"], cursor)
                for line in page["lines"]:
                    print(line)
                return int(ExitCode.OK)
            time.sleep(args.interval)
    finally:
        client.close()


def _report_from_dict(report: dict[str, Any]) -> PreflightReport:
    checks = tuple(
        PreflightCheck(
            code=item["code"],
            title=item["title"],
            status=item["status"],
            message=item["message"],
            detail=item.get("detail") or {},
        )
        for item in report["checks"]
    )
    return PreflightReport(
        host=report["host"],
        checked_at=report["checked_at"],
        checks=checks,
        gate=report.get("gate") or Gate.bootstrap.value,
    )


def _add_api_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--api-url", default=None, help="后端地址")
    parser.add_argument("--token", default=None, help="Bearer Token")
    parser.add_argument("--agent-id", default=None, help="Agent ID")
    parser.add_argument("--environment-id", default=None, help="指定 Environment")
    parser.add_argument("--json", action="store_true", help="输出单个 JSON 文档")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="witty-service openfuyao",
        description="openFuyao Bootstrap 编排工具",
        epilog=(
            "退出码：0 成功（含幂等）/ 1 执行错误 / 2 需要 --confirm / "
            "3 预检未通过 / 4 终态非目标"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser(
        "preflight",
        help="只读门禁：bootstrap=干净宿主，node=加入业务集群",
    )
    preflight.add_argument(
        "--gate",
        choices=[gate.value for gate in Gate],
        default=Gate.bootstrap.value,
        help="门禁场景（默认 bootstrap）",
    )
    preflight.add_argument("--json", action="store_true", help="输出 JSON")
    preflight.set_defaults(handler=_cmd_preflight)

    deploy = subparsers.add_parser("deploy", help="创建环境并发起 Bootstrap")
    _add_api_options(deploy)
    deploy.add_argument("--dry-run", action="store_true", help="只预检，不落库")
    deploy.add_argument(
        "--confirm", action="store_true", help="确认执行破坏性的 bke init"
    )
    deploy.add_argument("--wait", action="store_true", help="等待到终态")
    deploy.add_argument("--timeout", type=float, default=_DEFAULT_TIMEOUT)
    deploy.add_argument("--interval", type=float, default=3.0)
    deploy.set_defaults(handler=_cmd_deploy)

    status = subparsers.add_parser("status", help="查看环境状态")
    _add_api_options(status)
    status.add_argument("--wait", action="store_true", help="等待到终态")
    status.add_argument("--timeout", type=float, default=_DEFAULT_TIMEOUT)
    status.add_argument("--interval", type=float, default=3.0)
    status.set_defaults(handler=_cmd_status)

    cancel = subparsers.add_parser("cancel", help="取消进行中的 Bootstrap")
    _add_api_options(cancel)
    cancel.set_defaults(handler=_cmd_cancel)

    logs = subparsers.add_parser("logs", help="读取 Bootstrap 日志")
    _add_api_options(logs)
    logs.add_argument("--cursor", type=int, default=0)
    logs.add_argument("--follow", action="store_true", help="持续跟随")
    logs.add_argument("--interval", type=float, default=1.0)
    logs.set_defaults(handler=_cmd_logs)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    # CLI 只输出业务结果；httpx 的逐请求 INFO 日志会淹没 Agent 可读输出。
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = build_parser()
    args: Any = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except _ApiError as exc:
        print(f"错误 [{exc.code}] {exc}", file=sys.stderr)
        return int(ExitCode.ERROR)


if __name__ == "__main__":
    sys.exit(main())
