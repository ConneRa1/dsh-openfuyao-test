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


# ==============================================================================
# 阶段 2/3：集群 / 节点 / 应用
# ==============================================================================


class ClusterNodeRequest(BaseModel):
    ip: str = Field(min_length=1)
    hostname: str = Field(min_length=1)
    role: Literal["master", "worker"] = "worker"
    port: int = 22
    username: str | None = None


class CreateClusterRequest(BaseModel):
    agent_id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=63)
    nodes: list[ClusterNodeRequest] = Field(default_factory=list)
    confirm: bool = False
    dry_run: bool = False


class ClusterPreflightRequest(BaseModel):
    agent_id: str = Field(min_length=1)
    name: str = "bke-preflight"
    nodes: list[ClusterNodeRequest] = Field(default_factory=list)


class ClusterNodeResponse(BaseModel):
    ip: str
    hostname: str
    port: int
    username: str
    role: str
    is_local: bool
    status: str
    phase: str
    error_code: str | None = None
    last_message: str | None = None

    @classmethod
    def from_record(cls, record: Any) -> ClusterNodeResponse:
        return cls(
            ip=record.ip,
            hostname=record.hostname,
            port=record.port,
            username=record.username,
            role=record.role,
            is_local=record.is_local,
            status=record.status,
            phase=record.phase,
            error_code=record.error_code,
            last_message=record.last_message,
        )


class ClusterResponse(BaseModel):
    id: str
    agent_id: str
    name: str
    namespace: str
    status: str
    phase: str
    progress: int
    expected_node_count: int
    endpoint: str | None = None
    kubeconfig_path: str | None = None
    preflight: dict[str, Any] | None = None
    nodes: list[ClusterNodeResponse] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    started_at: UtcDatetime | None = None
    finished_at: UtcDatetime | None = None

    @classmethod
    def from_record(
        cls,
        record: Any,
        nodes: list[Any] | None = None,
    ) -> ClusterResponse:
        return cls(
            id=record.id,
            agent_id=record.agent_id,
            name=record.name,
            namespace=record.namespace,
            status=record.status,
            phase=record.phase,
            progress=record.progress,
            expected_node_count=record.expected_node_count,
            endpoint=record.endpoint,
            kubeconfig_path=record.kubeconfig_path,
            preflight=record.preflight_json,
            nodes=[ClusterNodeResponse.from_record(item) for item in nodes or []],
            error_code=record.error_code,
            error_message=record.error_message,
            created_at=record.created_at,
            updated_at=record.updated_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
        )


class ClusterConsoleResponse(BaseModel):
    """业务控制台入口；``url`` 为空时用 ``reason`` 解释为什么不可用。"""

    available: bool
    url: str | None = None
    reason: str | None = None


class CreateClusterResponse(BaseModel):
    cluster: ClusterResponse | None
    plan: list[dict[str, str | int]]
    created: bool
    needs_confirm: bool = False


class ClusterPreflightFailureResponse(BaseModel):
    rule_id: str
    subject: str
    status: str
    node_ip: str | None = None
    code: str
    message: str
    remediation: str = ""


class ClusterPreflightResponse(BaseModel):
    ready: bool
    summary: str
    failures: list[ClusterPreflightFailureResponse]
    tolerated: list[ClusterPreflightFailureResponse]
    preflight: dict[str, Any]


class AppInstallRequest(BaseModel):
    agent_id: str = Field(min_length=1)
    cluster: str = Field(min_length=1)
    release_name: str = Field(min_length=1, max_length=63)
    namespace: str = "default"
    chart_dir: str | None = None
    repo_url: str | None = None
    chart: str | None = None
    chart_version: str | None = None
    values: dict[str, Any] = Field(default_factory=dict)
    image: str | None = None
    node_port: int | None = None
    verify_url: str | None = None
    confirm: bool = False


class AppResponse(BaseModel):
    id: str
    cluster_id: str
    agent_id: str
    namespace: str
    release_name: str
    chart_name: str | None = None
    chart_version: str | None = None
    image_override: str | None = None
    status: str
    phase: str
    progress: int
    node_port: int | None = None
    verify_url: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    started_at: UtcDatetime | None = None
    finished_at: UtcDatetime | None = None

    @classmethod
    def from_record(cls, record: Any) -> AppResponse:
        return cls(
            id=record.id,
            cluster_id=record.cluster_id,
            agent_id=record.agent_id,
            namespace=record.namespace,
            release_name=record.release_name,
            chart_name=record.chart_name,
            chart_version=record.chart_version,
            image_override=record.image_override,
            status=record.status,
            phase=record.phase,
            progress=record.progress,
            node_port=record.node_port,
            verify_url=record.verify_url,
            error_code=record.error_code,
            error_message=record.error_message,
            created_at=record.created_at,
            updated_at=record.updated_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
        )


class CreateAppResponse(BaseModel):
    app: AppResponse | None
    created: bool
    needs_confirm: bool = False


class OpenFuyaoIssueResponse(BaseModel):
    """控制台资源的一条可执行诊断结论。"""

    id: str
    code: str
    severity: Literal["info", "warn", "error"]
    source: str
    title: str
    message: str
    remediation: str = ""
    resource_id: str | None = None
    resource_name: str | None = None


class ConsoleSessionProbeResponse(BaseModel):
    """引导节点控制台入口的 Cookie 透传探测结果。

    ``session_capable`` 只能证明 Cookie 被 console-service 读到（``True``）；老版本
    bke-console 对未知会话固定回 ``cookie not found``，无法与“入口丢 Cookie”区分，
    此时返回 ``None``。前端不应据此把引导节点控制台替换成业务控制台。
    """

    url: str | None = None
    reachable: bool
    session_capable: bool | None = None
    reason: str | None = None


class OpenFuyaoOverviewResponse(BaseModel):
    """PolyMind 感知到的 openFuyao 当前状态。

    ``clusters``/``apps`` 是**纳管后的数据库对象**，包含了从控制台发现并导入的
    集群和应用；``issues`` 是可直接展示/交给 Agent 的诊断结论。
    """

    clusters: list[ClusterResponse]
    apps: list[AppResponse]
    issues: list[OpenFuyaoIssueResponse]
    console: ClusterConsoleResponse
    #: 引导节点控制台探测；仅用于诊断，不驱动前端切换控制台地址。
    guide_console: ConsoleSessionProbeResponse | None = None
    refreshed_at: str
    discovered: bool = True
    errors: list[str] = Field(default_factory=list)


class AppPreflightRequest(BaseModel):
    agent_id: str = Field(min_length=1)
    cluster: str = Field(min_length=1)
    release_name: str = Field(min_length=1, max_length=63)
    namespace: str = "default"
    chart_dir: str | None = None
    repo_url: str | None = None
    chart: str | None = None
    chart_version: str | None = None
    image: str | None = None
    node_port: int | None = None


class AppPreflightCheckResponse(BaseModel):
    code: str
    status: Literal["pass", "warn", "fail"]
    title: str
    message: str
    remediation: str = ""


class AppPreflightResponse(BaseModel):
    ready: bool
    summary: str
    checks: list[AppPreflightCheckResponse]
