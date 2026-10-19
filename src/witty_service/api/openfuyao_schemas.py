"""openFuyao Environment API 的请求/响应模型。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from witty_service.api.schemas import UtcDatetime
from witty_service.persistence.openfuyao_repository import OpenFuyaoEnvironmentRecord

CheckStatus = Literal["pass", "warn", "fail"]


class CreateEnvironmentRequest(BaseModel):
    agent_id: str = Field(min_length=1)
    dry_run: bool = False


class BootstrapRequest(BaseModel):
    confirm: bool = False


class PreflightCheckResponse(BaseModel):
    code: str
    title: str
    status: CheckStatus
    message: str
    detail: dict[str, Any] = Field(default_factory=dict)


class PreflightReportResponse(BaseModel):
    host: str
    checked_at: str
    ready: bool
    summary: dict[str, int]
    checks: list[PreflightCheckResponse]


class EnvironmentResponse(BaseModel):
    id: str
    agent_id: str
    host: str
    status: str
    phase: str
    progress: int
    console_url: str | None = None
    proxy_url: str | None = None
    bke_version: str | None = None
    os_version: str | None = None
    preflight: PreflightReportResponse | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    started_at: UtcDatetime | None = None
    finished_at: UtcDatetime | None = None

    @classmethod
    def from_record(cls, record: OpenFuyaoEnvironmentRecord) -> EnvironmentResponse:
        preflight = (
            PreflightReportResponse.model_validate(record.preflight_json)
            if record.preflight_json
            else None
        )
        return cls(
            id=record.id,
            agent_id=record.agent_id,
            host=record.host,
            status=record.status,
            phase=record.phase,
            progress=record.progress,
            console_url=record.console_url,
            proxy_url=record.proxy_url,
            bke_version=record.bke_version,
            os_version=record.os_version,
            preflight=preflight,
            error_code=record.error_code,
            error_message=record.error_message,
            created_at=record.created_at,
            updated_at=record.updated_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
        )


class CreateEnvironmentResponse(BaseModel):
    environment: EnvironmentResponse | None
    preflight: PreflightReportResponse
    plan: list[dict[str, str | int]]
    created: bool


class EnvironmentLogsResponse(BaseModel):
    cursor: int
    next_cursor: int
    lines: list[str]
    eof: bool


class EnvironmentHealthResponse(BaseModel):
    console_reachable: bool
    http_status: int | None = None
    console_url: str
    proxy_url: str | None = None
    error: str | None = None
