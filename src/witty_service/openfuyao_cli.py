"""openFuyao 运维 CLI（``witty-service openfuyao ...``）。

- ``preflight``：只读宿主机门禁，不依赖后端；
- ``observe``：感知控制台侧手工创建的集群/应用并返回诊断（Agent 回答状态问题前必跑）；
- ``deploy/status/cancel/logs``：通过本机 REST API 驱动编排，Agent 不需要拼 ``bke``；
- ``cluster list/status/logs``：只读感知；``cluster create`` 已停用，业务集群走控制台；
- ``app preflight/install/rollback/uninstall``：应用预检、安装、回滚、卸载。

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
from pathlib import Path
from typing import Any

import httpx

from witty_service.application.openfuyao.cluster_spec import (
    parse_node_argument,
    parse_nodes_file,
)
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

    observe = subparsers.add_parser(
        "observe", help="感知控制台侧集群/应用并给出诊断"
    )
    _add_api_options(observe)
    observe.set_defaults(handler=_cmd_observe)

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

    _add_cluster_parsers(subparsers)
    _add_app_parsers(subparsers)

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
        # 本地门禁类错误（hostname/IP/凭据/预检）与阶段 1 一样退 3，
        # Agent 才能把“节点参数不合法”和“API 挂了”分开处理。
        return int(_exit_for_error(exc.code))



# ==============================================================================
# 感知：控制台侧集群/应用 + 诊断
# ==============================================================================


def _cmd_observe(args: argparse.Namespace) -> int:
    """读取统一快照；这是 Agent 回答“现在有什么/哪里坏了”的唯一事实来源。"""
    client = _client(args)
    try:
        overview = client.request(
            "GET", "/openfuyao/overview", params={"agent_id": _agent_id(args)}
        )
        if args.json:
            print(json.dumps(overview, ensure_ascii=False, indent=2))
            return int(ExitCode.OK)
        clusters = overview.get("clusters") or []
        apps = overview.get("apps") or []
        issues = overview.get("issues") or []
        print(f"openFuyao 感知：{len(clusters)} 个集群，{len(apps)} 个应用，{len(issues)} 条诊断")
        print("-" * 72)
        for cluster in clusters:
            print(
                f"[集群] {cluster['name']:<24} {cluster['status']:<14} "
                f"{cluster.get('endpoint') or ''}"
            )
        for app in apps:
            print(
                f"[应用] {app['release_name']:<24} ns={app['namespace']:<16} "
                f"{app['status']:<10} {app.get('verify_url') or ''}"
            )
        for issue in issues:
            print(
                f"[{issue['severity'].upper():5}] {issue['code']:<28} "
                f"{issue['title']}：{issue['message'][:160]}"
            )
            if issue.get("remediation"):
                print(f"        建议：{issue['remediation']}")
        for error in overview.get("errors") or []:
            print(f"[感知降级] {error}")
        return int(ExitCode.OK)
    finally:
        client.close()


# ==============================================================================
# 阶段 2：集群
# ==============================================================================

_CLUSTER_TERMINAL = frozenset({"ready", "failed", "cancelled"})
_APP_TERMINAL = frozenset({"deployed", "failed", "cancelled"})

#: 这些错误码说明“门禁没过”，CLI 统一退出 3，便于 Agent 与阶段 1 用同一套分流。
_PREFLIGHT_ERROR_CODES = frozenset(
    {
        ErrorCode.PREFLIGHT_FAILED,
        ErrorCode.HOSTNAME_INVALID,
        ErrorCode.NODE_UNREACHABLE,
        ErrorCode.NODE_PRIVILEGE_MISSING,
        ErrorCode.NODE_CPU_INSUFFICIENT,
        ErrorCode.NODE_DISK_INSUFFICIENT,
        ErrorCode.NODE_ROLE_INVALID,
        ErrorCode.NODE_CREDENTIAL_MISSING,
        ErrorCode.MEMORY_INSUFFICIENT,
    }
)


def _exit_for_error(code: str) -> ExitCode:
    return (
        ExitCode.PREFLIGHT_FAILED
        if code in _PREFLIGHT_ERROR_CODES
        else ExitCode.ERROR
    )


def _collect_nodes(args: argparse.Namespace) -> list[dict[str, Any]]:
    """合并 ``--nodes-file`` 与重复的 ``--node``；密码不在这里出现。"""
    nodes: list[dict[str, Any]] = []
    if getattr(args, "nodes_file", None):
        try:
            payload = json.loads(Path(args.nodes_file).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise _ApiError(
                0, ErrorCode.NODE_ROLE_INVALID, f"节点文件不可读：{exc}"
            ) from exc
        nodes.extend(parse_nodes_file(payload))
    for raw in getattr(args, "node", None) or []:
        nodes.append(dict(parse_node_argument(raw)))
    return nodes


def _print_cluster(cluster: dict[str, Any]) -> None:
    print(
        "集群 {name}  status={status} phase={phase} progress={progress}%".format(
            **cluster
        )
    )
    if cluster.get("endpoint"):
        print(f"  endpoint:   {cluster['endpoint']}")
    if cluster.get("kubeconfig_path"):
        print(f"  kubeconfig: {cluster['kubeconfig_path']}")
    if cluster.get("error_code"):
        print(
            f"  error:      {cluster['error_code']} "
            f"{cluster.get('error_message') or ''}"
        )
    nodes = cluster.get("nodes") or []
    if nodes:
        print("  节点:")
        for node in nodes:
            marker = "local" if node.get("is_local") else "     "
            text = (
                f"    [{node['role']:<6}] {node['ip']:<15} {node['hostname']:<20} "
                f"{node['status']:<14} {marker}"
            )
            if node.get("error_code"):
                text += f" {node['error_code']}: {(node.get('last_message') or '')[:60]}"
            print(text)


def _print_nodes_table(nodes: Sequence[dict[str, Any]]) -> None:
    print("节点：")
    for node in nodes:
        print(
            f"  [{node.get('role', 'worker'):<6}] {node.get('ip', ''):<15} "
            f"{node.get('hostname', ''):<20} port={node.get('port', 22)}"
        )


def _cluster_summary(cluster: dict[str, Any]) -> str:
    status = cluster["status"]
    if status == "ready":
        return f"集群 {cluster['name']} 已就绪，endpoint={cluster.get('endpoint') or ''}"
    if status == "failed":
        return (
            f"集群 {cluster['name']} 创建失败：{cluster.get('error_code') or ''} "
            f"{cluster.get('error_message') or ''}"
        )
    if status == "cancelled":
        return f"集群 {cluster['name']} 已取消"
    return f"集群 {cluster['name']} 正在创建（{cluster['status']} / {cluster['phase']}）"


def _cluster_exit(cluster: dict[str, Any]) -> ExitCode:
    status = cluster["status"]
    if status == "ready":
        return ExitCode.OK
    if status in ("failed", "cancelled"):
        if cluster.get("error_code") in _PREFLIGHT_ERROR_CODES:
            return ExitCode.PREFLIGHT_FAILED
        return ExitCode.FAILED
    return ExitCode.OK


def _finish_cluster(
    args: argparse.Namespace,
    *,
    exit_code: ExitCode,
    summary: str,
    cluster: dict[str, Any] | None,
    plan: Sequence[dict[str, Any]],
    nodes: Sequence[dict[str, Any]] | None = None,
    needs_confirm: bool = False,
) -> int:
    if args.json:
        print(
            json.dumps(
                {
                    "exit_code": int(exit_code),
                    "needs_confirm": needs_confirm,
                    "summary": summary,
                    "cluster": cluster,
                    "nodes": list(
                        (cluster.get("nodes") if cluster else None) or nodes or []
                    ),
                    "plan": list(plan),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return int(exit_code)
    if cluster is not None:
        _print_cluster(cluster)
    elif nodes:
        _print_nodes_table(nodes)
    _print_plan(plan)
    print("")
    print(summary)
    return int(exit_code)


def _cluster_id_or_latest(client: _Client, args: argparse.Namespace) -> dict[str, Any]:
    if getattr(args, "cluster_id", None):
        return client.request("GET", f"/openfuyao/clusters/{args.cluster_id}")
    clusters = client.request(
        "GET", "/openfuyao/clusters", params={"agent_id": _agent_id(args)}
    )
    if not clusters:
        raise _ApiError(404, ErrorCode.CLUSTER_NOT_FOUND, "该 Agent 还没有业务集群")
    if getattr(args, "name", None):
        for cluster in clusters:
            if cluster["name"] == args.name:
                return cluster
        raise _ApiError(
            404, ErrorCode.CLUSTER_NOT_FOUND, f"集群 {args.name} 不存在"
        )
    return clusters[0]


def _poll_cluster(
    client: _Client,
    cluster: dict[str, Any],
    *,
    timeout: float,
    interval: float,
    quiet: bool = False,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    current = cluster
    previous: tuple[str, str] | None = None
    while True:
        signature = (current["status"], current["phase"])
        if signature != previous:
            if not quiet:
                _print_cluster(current)
            previous = signature
        if current["status"] in _CLUSTER_TERMINAL:
            return current
        if time.monotonic() >= deadline:
            raise _ApiError(0, ErrorCode.WAIT_TIMEOUT, f"等待超过 {int(timeout)}s")
        time.sleep(interval)
        current = client.request("GET", f"/openfuyao/clusters/{current['id']}")


def _cmd_cluster_create(args: argparse.Namespace) -> int:
    client = _client(args)
    try:
        nodes = _collect_nodes(args)
        result = client.request(
            "POST",
            "/openfuyao/clusters",
            json={
                "agent_id": _agent_id(args),
                "name": args.name,
                "nodes": nodes,
                "confirm": args.confirm,
                "dry_run": args.dry_run,
            },
        )
        plan = result.get("plan") or []
        cluster = result.get("cluster")
        if result.get("needs_confirm"):
            summary = (
                f"将在 {_agent_id(args)} 的环境上创建业务集群 {args.name}；"
                "加 --confirm 才会执行 bke cluster create（会改动节点）。"
            )
            return _finish_cluster(
                args,
                exit_code=ExitCode.CONFIRM_REQUIRED,
                summary=summary,
                cluster=None,
                plan=plan,
                nodes=nodes,
                needs_confirm=True,
            )
        if cluster is None:
            return _finish_cluster(
                args,
                exit_code=ExitCode.OK,
                summary="dry-run：只做了本地校验，未创建集群。",
                cluster=None,
                plan=plan,
                nodes=nodes,
            )
        if args.wait:
            cluster = _poll_cluster(
                client,
                cluster,
                timeout=args.timeout,
                interval=args.interval,
                quiet=args.json,
            )
        return _finish_cluster(
            args,
            exit_code=_cluster_exit(cluster),
            summary=_cluster_summary(cluster),
            cluster=cluster,
            plan=plan,
        )
    finally:
        client.close()


def _cmd_cluster_create_disabled(args: argparse.Namespace) -> int:
    del args
    print(
        "阶段 2 已改为在引导节点控制台手动创建业务集群；PolyMind 只负责感知、"
        "诊断和应用安装。请打开面板“引导节点控制台”Tab 创建集群。",
        file=sys.stderr,
    )
    return int(ExitCode.ERROR)


def _cmd_cluster_preflight(args: argparse.Namespace) -> int:
    client = _client(args)
    try:
        nodes = _collect_nodes(args)
        result = client.request(
            "POST",
            "/openfuyao/clusters/preflight",
            json={
                "agent_id": _agent_id(args),
                "name": args.name,
                "nodes": nodes,
            },
            timeout=1200.0,
        )
        failures = result.get("failures") or []
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"节点预检：{result['summary']}")
            for item in failures:
                print(
                    f"  [FAIL] {item['code']:<24} {item['subject']:<24} "
                    f"{item['message'][:100]}"
                )
                if item.get("remediation"):
                    print(f"         建议：{item['remediation']}")
            for item in result.get("tolerated") or []:
                print(f"  [WARN] {item['rule_id']} 已按 OS 矩阵例外放行")
        return int(ExitCode.OK if result["ready"] else ExitCode.PREFLIGHT_FAILED)
    finally:
        client.close()


def _cmd_cluster_status(args: argparse.Namespace) -> int:
    client = _client(args)
    try:
        cluster = _cluster_id_or_latest(client, args)
        if args.wait:
            cluster = _poll_cluster(
                client,
                cluster,
                timeout=args.timeout,
                interval=args.interval,
                quiet=args.json,
            )
        if args.json:
            print(json.dumps(cluster, ensure_ascii=False, indent=2))
        else:
            _print_cluster(cluster)
        return int(_cluster_exit(cluster))
    finally:
        client.close()


def _cmd_cluster_list(args: argparse.Namespace) -> int:
    client = _client(args)
    try:
        clusters = client.request(
            "GET", "/openfuyao/clusters", params={"agent_id": _agent_id(args)}
        )
        if args.json:
            print(json.dumps(clusters, ensure_ascii=False, indent=2))
        else:
            for cluster in clusters:
                print(
                    f"{cluster['name']:<24} {cluster['status']:<14} "
                    f"{cluster['phase']:<14} {cluster['progress']:>3}%  "
                    f"{cluster.get('endpoint') or ''}"
                )
        return int(ExitCode.OK)
    finally:
        client.close()


def _cmd_cluster_destroy(args: argparse.Namespace) -> int:
    client = _client(args)
    try:
        cluster = _cluster_id_or_latest(client, args)
        if not args.confirm:
            print(
                f"将删除集群 {cluster['name']} 的 BKECluster；节点上的 kubelet/控制面不会自动卸载。"
                " 加 --confirm 才会执行。",
                file=sys.stderr,
            )
            return int(ExitCode.CONFIRM_REQUIRED)
        result = client.request(
            "DELETE",
            f"/openfuyao/clusters/{cluster['id']}",
            params={"confirm": True},
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"集群 {result['destroyed']} 的 BKECluster 已删除。")
            print("以下节点仍可能残留 kubelet/控制面，需要重装或手工清理：")
            for item in result.get("nodes_dirty") or []:
                print(
                    f"  [{item['role']:<6}] {item['ip']:<15} {item['hostname']}"
                )
        return int(ExitCode.OK)
    finally:
        client.close()


def _cmd_cluster_logs(args: argparse.Namespace) -> int:
    client = _client(args)
    try:
        cluster = _cluster_id_or_latest(client, args)
        cursor = args.cursor
        while True:
            page = client.request(
                "GET",
                f"/openfuyao/clusters/{cluster['id']}/logs",
                params={"cursor": cursor},
            )
            for line in page["lines"]:
                print(line)
            cursor = page["next_cursor"]
            if not args.follow or page["eof"]:
                return int(ExitCode.OK)
            cluster = client.request("GET", f"/openfuyao/clusters/{cluster['id']}")
            if cluster["status"] in _CLUSTER_TERMINAL:
                page = client.request(
                    "GET",
                    f"/openfuyao/clusters/{cluster['id']}/logs",
                    params={"cursor": cursor},
                )
                for line in page["lines"]:
                    print(line)
                return int(_cluster_exit(cluster))
            time.sleep(args.interval)
    finally:
        client.close()


# ==============================================================================
# 阶段 3：应用
# ==============================================================================


def _print_app(app: dict[str, Any]) -> None:
    print(
        "应用 {release_name}  ns={namespace}  status={status} phase={phase} "
        "progress={progress}%".format(**app)
    )
    if app.get("chart_name"):
        print(f"  chart:    {app['chart_name']} {app.get('chart_version') or ''}")
    if app.get("image_override"):
        print(f"  image:    {app['image_override']}")
    if app.get("verify_url"):
        print(f"  url:      {app['verify_url']}")
    if app.get("error_code"):
        print(f"  error:    {app['error_code']} {app.get('error_message') or ''}")


def _app_exit(app: dict[str, Any]) -> ExitCode:
    if app["status"] == "deployed":
        return ExitCode.OK
    if app["status"] in ("failed", "cancelled"):
        return ExitCode.FAILED
    return ExitCode.OK


def _poll_app(
    client: _Client,
    app: dict[str, Any],
    *,
    timeout: float,
    interval: float,
    quiet: bool = False,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    current = app
    previous: str | None = None
    while True:
        if current["status"] != previous:
            if not quiet:
                _print_app(current)
            previous = current["status"]
        if current["status"] in _APP_TERMINAL:
            return current
        if time.monotonic() >= deadline:
            raise _ApiError(0, ErrorCode.WAIT_TIMEOUT, f"等待超过 {int(timeout)}s")
        time.sleep(interval)
        current = client.request("GET", f"/openfuyao/apps/{current['id']}")


def _cmd_app_install(args: argparse.Namespace) -> int:
    client = _client(args)
    try:
        values: dict[str, Any] = {}
        if args.values:
            try:
                parsed = json.loads(args.values)
            except ValueError as exc:
                raise _ApiError(
                    0, ErrorCode.APP_INSTALL_FAILED, f"--values 不是合法 JSON：{exc}"
                ) from exc
            if not isinstance(parsed, dict):
                raise _ApiError(
                    0, ErrorCode.APP_INSTALL_FAILED, "--values 必须是 JSON 对象"
                )
            values = parsed
        result = client.request(
            "POST",
            "/openfuyao/apps",
            json={
                "agent_id": _agent_id(args),
                "cluster": args.cluster,
                "release_name": args.release,
                "namespace": args.namespace,
                "chart_dir": args.chart_dir,
                "repo_url": args.repo_url,
                "chart": args.chart,
                "chart_version": args.chart_version,
                "values": values,
                "image": args.image,
                "node_port": args.node_port,
                "verify_url": args.verify_url,
                "confirm": args.confirm,
            },
        )
        app = result.get("app")
        if result.get("needs_confirm"):
            message = (
                f"将在集群 {args.cluster} 安装 {args.release}（ns={args.namespace}）；"
                "加 --confirm 才会执行 helm。"
            )
            if args.json:
                print(
                    json.dumps(
                        {
                            "exit_code": int(ExitCode.CONFIRM_REQUIRED),
                            "needs_confirm": True,
                            "summary": message,
                            "app": app,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            else:
                print(message)
            return int(ExitCode.CONFIRM_REQUIRED)
        if app is None:
            raise _ApiError(0, ErrorCode.APP_INSTALL_FAILED, "服务未返回应用记录")
        if args.wait:
            app = _poll_app(
                client,
                app,
                timeout=args.timeout,
                interval=args.interval,
                quiet=args.json,
            )
        if args.json:
            print(
                json.dumps(
                    {
                        "exit_code": int(_app_exit(app)),
                        "needs_confirm": False,
                        "summary": (
                            f"{app['release_name']} 已部署，url={app.get('verify_url') or ''}"
                            if app["status"] == "deployed"
                            else f"{app['release_name']} 未成功：{app['status']}"
                        ),
                        "app": app,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            _print_app(app)
        return int(_app_exit(app))
    finally:
        client.close()


def _cmd_app_status(args: argparse.Namespace) -> int:
    client = _client(args)
    try:
        if args.app_id:
            app = client.request("GET", f"/openfuyao/apps/{args.app_id}")
        else:
            params: dict[str, Any] = {"agent_id": _agent_id(args)}
            if args.cluster:
                clusters = client.request(
                    "GET", "/openfuyao/clusters", params={"agent_id": _agent_id(args)}
                )
                match = [item for item in clusters if item["name"] == args.cluster]
                if not match:
                    raise _ApiError(
                        404, ErrorCode.CLUSTER_NOT_FOUND, f"集群 {args.cluster} 不存在"
                    )
                params["cluster_id"] = match[0]["id"]
            apps = client.request("GET", "/openfuyao/apps", params=params)
            if not apps:
                raise _ApiError(404, ErrorCode.APP_NOT_FOUND, "还没有应用记录")
            app = apps[0]
        if args.wait:
            app = _poll_app(
                client,
                app,
                timeout=args.timeout,
                interval=args.interval,
                quiet=args.json,
            )
        if args.json:
            print(json.dumps(app, ensure_ascii=False, indent=2))
        else:
            _print_app(app)
        return int(_app_exit(app))
    finally:
        client.close()


def _cmd_app_list(args: argparse.Namespace) -> int:
    client = _client(args)
    try:
        apps = client.request(
            "GET", "/openfuyao/apps", params={"agent_id": _agent_id(args)}
        )
        if args.json:
            print(json.dumps(apps, ensure_ascii=False, indent=2))
        else:
            for app in apps:
                print(
                    f"{app['release_name']:<24} ns={app['namespace']:<16} "
                    f"{app['status']:<12} {app.get('verify_url') or ''}"
                )
        return int(ExitCode.OK)
    finally:
        client.close()


def _app_ref(client: _Client, args: argparse.Namespace) -> dict[str, Any]:
    if getattr(args, "app_id", None):
        return client.request("GET", f"/openfuyao/apps/{args.app_id}")
    params: dict[str, Any] = {"agent_id": _agent_id(args)}
    apps = client.request("GET", "/openfuyao/apps", params=params)
    if getattr(args, "cluster", None):
        clusters = client.request(
            "GET", "/openfuyao/clusters", params={"agent_id": _agent_id(args)}
        )
        match = [item for item in clusters if item["name"] == args.cluster]
        if not match:
            raise _ApiError(404, ErrorCode.CLUSTER_NOT_FOUND, f"集群 {args.cluster} 不存在")
        apps = [item for item in apps if item["cluster_id"] == match[0]["id"]]
    if getattr(args, "release", None):
        apps = [item for item in apps if item["release_name"] == args.release]
    if not apps:
        raise _ApiError(404, ErrorCode.APP_NOT_FOUND, "没有匹配的应用记录")
    return apps[0]


def _cmd_app_preflight(args: argparse.Namespace) -> int:
    client = _client(args)
    try:
        result = client.request(
            "POST",
            "/openfuyao/apps/preflight",
            json={
                "agent_id": _agent_id(args),
                "cluster": args.cluster,
                "release_name": args.release,
                "namespace": args.namespace,
                "chart_dir": args.chart_dir,
                "repo_url": args.repo_url,
                "chart": args.chart,
                "chart_version": args.chart_version,
                "image": args.image,
                "node_port": args.node_port,
            },
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"应用预检：{result['summary']}")
            for item in result["checks"]:
                print(
                    f"  [{item['status'].upper():4}] {item['title']:<16} "
                    f"{item['message'][:120]}"
                )
                if item.get("remediation"):
                    print(f"         建议：{item['remediation']}")
        return int(ExitCode.OK if result["ready"] else ExitCode.PREFLIGHT_FAILED)
    finally:
        client.close()


def _cmd_app_rollback(args: argparse.Namespace) -> int:
    client = _client(args)
    try:
        app = _app_ref(client, args)
        if not args.confirm:
            print(
                f"将把 {app['namespace']}/{app['release_name']} 回滚到 "
                f"{'上一版本' if args.revision is None else f'revision {args.revision}'}；"
                "加 --confirm 才会执行。",
                file=sys.stderr,
            )
            return int(ExitCode.CONFIRM_REQUIRED)
        params: dict[str, Any] = {"confirm": True}
        if args.revision is not None:
            params["revision"] = args.revision
        updated = client.request(
            "POST", f"/openfuyao/apps/{app['id']}/rollback", params=params
        )
        if args.json:
            print(json.dumps(updated, ensure_ascii=False, indent=2))
        else:
            _print_app(updated)
        return int(ExitCode.OK)
    finally:
        client.close()


def _cmd_app_uninstall(args: argparse.Namespace) -> int:
    client = _client(args)
    try:
        app = _app_ref(client, args)
        if not args.confirm:
            print(
                f"将卸载 {app['namespace']}/{app['release_name']}；加 --confirm 才会执行。",
                file=sys.stderr,
            )
            return int(ExitCode.CONFIRM_REQUIRED)
        result = client.request(
            "DELETE", f"/openfuyao/apps/{app['id']}", params={"confirm": True}
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"应用 {app['release_name']} 已卸载。")
        return int(ExitCode.OK)
    finally:
        client.close()


def _add_cluster_parsers(subparsers: Any) -> None:
    cluster = subparsers.add_parser("cluster", help="阶段 2：业务集群")
    cluster_sub = cluster.add_subparsers(dest="cluster_command", required=True)

    create = cluster_sub.add_parser(
        "create", help="已停用：业务集群改为在引导节点控制台手动创建"
    )
    _add_api_options(create)
    create.set_defaults(handler=_cmd_cluster_create_disabled)

    preflight = cluster_sub.add_parser("preflight", help="同步跑节点预检")
    _add_api_options(preflight)
    preflight.add_argument("--name", default="bke-preflight")
    preflight.add_argument("--node", action="append", default=[])
    preflight.add_argument("--nodes-file", default=None)
    preflight.set_defaults(handler=_cmd_cluster_preflight)

    status = cluster_sub.add_parser("status", help="查看集群状态")
    _add_api_options(status)
    status.add_argument("--name", default=None)
    status.add_argument("--cluster-id", default=None)
    status.add_argument("--wait", action="store_true")
    status.add_argument("--timeout", type=float, default=2400.0)
    status.add_argument("--interval", type=float, default=5.0)
    status.set_defaults(handler=_cmd_cluster_status)

    list_cmd = cluster_sub.add_parser("list", help="列出集群")
    _add_api_options(list_cmd)
    list_cmd.set_defaults(handler=_cmd_cluster_list)

    destroy = cluster_sub.add_parser("destroy", help="只删 BKECluster（不清理节点）")
    _add_api_options(destroy)
    destroy.add_argument("--name", default=None)
    destroy.add_argument("--cluster-id", default=None)
    destroy.add_argument("--confirm", action="store_true")
    destroy.set_defaults(handler=_cmd_cluster_destroy)

    logs = cluster_sub.add_parser("logs", help="读取集群日志")
    _add_api_options(logs)
    logs.add_argument("--name", default=None)
    logs.add_argument("--cluster-id", default=None)
    logs.add_argument("--cursor", type=int, default=0)
    logs.add_argument("--follow", action="store_true")
    logs.add_argument("--interval", type=float, default=1.0)
    logs.set_defaults(handler=_cmd_cluster_logs)


def _add_app_parsers(subparsers: Any) -> None:
    app = subparsers.add_parser("app", help="阶段 3：应用安装")
    app_sub = app.add_subparsers(dest="app_command", required=True)

    install = app_sub.add_parser("install", help="helm 安装并验证")
    _add_api_options(install)
    install.add_argument("--cluster", required=True)
    install.add_argument("--release", required=True)
    install.add_argument("--namespace", default="default")
    install.add_argument("--chart-dir", default=None)
    install.add_argument("--repo-url", default=None)
    install.add_argument("--chart", default=None)
    install.add_argument("--chart-version", default=None)
    install.add_argument("--values", default=None, help="JSON 对象字符串")
    install.add_argument("--image", default=None, help="覆盖 image.repository/tag")
    install.add_argument("--node-port", type=int, default=None)
    install.add_argument("--verify-url", default=None)
    install.add_argument("--confirm", action="store_true")
    install.add_argument("--wait", action="store_true")
    install.add_argument("--timeout", type=float, default=1800.0)
    install.add_argument("--interval", type=float, default=5.0)
    install.set_defaults(handler=_cmd_app_install)

    app_preflight = app_sub.add_parser("preflight", help="安装前预检（集群/chart/端口）")
    _add_api_options(app_preflight)
    app_preflight.add_argument("--cluster", required=True)
    app_preflight.add_argument("--release", required=True)
    app_preflight.add_argument("--namespace", default="default")
    app_preflight.add_argument("--chart-dir", default=None)
    app_preflight.add_argument("--repo-url", default=None)
    app_preflight.add_argument("--chart", default=None)
    app_preflight.add_argument("--chart-version", default=None)
    app_preflight.add_argument("--image", default=None)
    app_preflight.add_argument("--node-port", type=int, default=None)
    app_preflight.set_defaults(handler=_cmd_app_preflight)

    rollback = app_sub.add_parser("rollback", help="回滚到上一 revision 或指定 revision")
    _add_api_options(rollback)
    rollback.add_argument("--app-id", default=None)
    rollback.add_argument("--cluster", default=None)
    rollback.add_argument("--release", default=None)
    rollback.add_argument("--revision", type=int, default=None)
    rollback.add_argument("--confirm", action="store_true")
    rollback.set_defaults(handler=_cmd_app_rollback)

    uninstall = app_sub.add_parser("uninstall", help="卸载 Helm release")
    _add_api_options(uninstall)
    uninstall.add_argument("--app-id", default=None)
    uninstall.add_argument("--cluster", default=None)
    uninstall.add_argument("--release", default=None)
    uninstall.add_argument("--confirm", action="store_true")
    uninstall.set_defaults(handler=_cmd_app_uninstall)

    status = app_sub.add_parser("status", help="查看应用状态")
    _add_api_options(status)
    status.add_argument("--app-id", default=None)
    status.add_argument("--cluster", default=None)
    status.add_argument("--wait", action="store_true")
    status.add_argument("--timeout", type=float, default=1800.0)
    status.add_argument("--interval", type=float, default=5.0)
    status.set_defaults(handler=_cmd_app_status)

    list_cmd = app_sub.add_parser("list", help="列出应用")
    _add_api_options(list_cmd)
    list_cmd.set_defaults(handler=_cmd_app_list)


if __name__ == "__main__":
    sys.exit(main())
