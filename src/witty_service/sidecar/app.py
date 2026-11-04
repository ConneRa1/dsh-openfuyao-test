"""FastAPI application exposed by the headless openFuyao sidecar."""

from __future__ import annotations

import json
import logging
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from witty_service.api.errors import register_exception_handlers
from witty_service.api.openfuyao import router as openfuyao_router
from witty_service.sidecar.config import SIDECAR_API_VERSION, SidecarConfig
from witty_service.sidecar.services import SidecarServices

logger = logging.getLogger(__name__)


def _client_host(host: str) -> str:
    if host in {"0.0.0.0", "::", ""}:
        return "127.0.0.1"
    return host


def _write_ready(config: SidecarConfig, port: int) -> None:
    payload = {
        "event": "ready",
        "url": f"http://{_client_host(config.host)}:{port}",
        "pid": os.getpid(),
        "apiVersion": SIDECAR_API_VERSION,
        "agentId": config.agent_id,
    }
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def create_sidecar_app(
    services: SidecarServices,
    *,
    config: SidecarConfig,
    port: int,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            services.recover_stale()
        except Exception:
            # Recovery is best-effort: a stale row must not make a healthy
            # database unusable, and the individual API calls still surface
            # their own errors.
            logger.exception("Sidecar recovery failed; continuing startup")
        _write_ready(config, port)
        try:
            yield
        finally:
            await services.close()

    app = FastAPI(
        title="openFuyao Sidecar",
        version=str(SIDECAR_API_VERSION),
        lifespan=lifespan,
    )
    app.state.services = services
    app.state.sidecar_config = config

    register_exception_handlers(app)
    app.include_router(openfuyao_router)

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {"status": "ok", "sidecar": SIDECAR_API_VERSION}

    @app.get("/sidecar/info")
    def info() -> dict[str, Any]:
        return {
            "service": "witty-service-openfuyao-sidecar",
            "sidecar": SIDECAR_API_VERSION,
            "pid": os.getpid(),
            "agent_id": config.agent_id,
            "workspace": str(config.workspace_root),
        }

    return app
