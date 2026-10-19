"""openFuyao 运维 CLI（``witty-service openfuyao ...``）。

先用 ``preflight`` 做只读门禁；后续 ``deploy/status/cancel/logs`` 通过本机
witty-service REST API 驱动编排，Agent 不需要自己拼 ``bke`` 命令。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from typing import Any

from witty_service.application.openfuyao.preflight import PreflightReport, run_preflight

_STATUS_MARK = {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}


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


def _cmd_preflight(args: argparse.Namespace) -> int:
    report = run_preflight()
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        _print_preflight(report)
    return 0 if report.ready else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="witty-service openfuyao",
        description="openFuyao Bootstrap 编排工具",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight = subparsers.add_parser("preflight", help="只读宿主机快检")
    preflight.add_argument("--json", action="store_true", help="输出 JSON")
    preflight.set_defaults(handler=_cmd_preflight)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args: Any = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    sys.exit(main())
