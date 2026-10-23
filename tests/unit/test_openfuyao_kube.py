"""业务控制台入口发现：NodePort 每次现查，端口不写死。"""

from __future__ import annotations

import json
from typing import Any

import pytest

from witty_service.application.openfuyao.kube import KubeClient
from witty_service.application.openfuyao.process import CommandResult

_SVC = {
    "spec": {
        "ports": [
            {"name": "http", "port": 80, "nodePort": 30080},
            {"name": "https", "port": 443, "nodePort": 31616},
        ]
    }
}

_NODES = {
    "items": [
        {
            "status": {
                "addresses": [
                    {"type": "InternalIP", "address": "192.0.2.10"},
                    {"type": "Hostname", "address": "auto-depoly"},
                ]
            }
        }
    ]
}


class _FakeRunner:
    """按 argv 里的资源名返回预置 JSON；未预置的命令返回非零（模拟看不到）。"""

    def __init__(self, payloads: dict[str, dict[str, Any]]) -> None:
        self._payloads = payloads
        self.calls: list[list[str]] = []

    async def run_capture(self, argv: list[str], timeout: float = 30.0) -> CommandResult:
        self.calls.append(list(argv))
        for key, payload in self._payloads.items():
            if key in argv:
                return CommandResult(returncode=0, output=json.dumps(payload))
        return CommandResult(returncode=1, output="")


@pytest.mark.asyncio
async def test_console_url_uses_ingress_node_port_and_endpoint_host() -> None:
    client = KubeClient(_FakeRunner({"ingress-nginx-controller": _SVC}), "/kc")
    endpoint = await client.resolve_console_url(host="192.0.2.10")
    assert endpoint.url == "https://192.0.2.10:31616/"
    assert endpoint.reason is None


@pytest.mark.asyncio
async def test_console_url_falls_back_to_first_node_address() -> None:
    client = KubeClient(
        _FakeRunner({"ingress-nginx-controller": _SVC, "nodes": _NODES}), "/kc"
    )
    endpoint = await client.resolve_console_url()
    assert endpoint.url == "https://192.0.2.10:31616/"


@pytest.mark.asyncio
async def test_console_url_reports_missing_ingress() -> None:
    client = KubeClient(_FakeRunner({}), "/kc")
    endpoint = await client.resolve_console_url(host="192.0.2.10")
    assert endpoint.url is None
    assert endpoint.reason == "ingress_not_ready"
