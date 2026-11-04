"""openFuyao Environment 端点。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Depends, Query, Request, Response, status

from witty_service.api.auth import require_bearer_auth
from witty_service.api.openfuyao_schemas import (
    AppInstallRequest,
    AppPreflightCheckResponse,
    AppPreflightRequest,
    AppPreflightResponse,
    AppResponse,
    BootstrapRequest,
    ClusterConsoleResponse,
    ClusterPreflightFailureResponse,
    ClusterPreflightRequest,
    ClusterPreflightResponse,
    ClusterResponse,
    ConsoleSessionProbeResponse,
    CreateAppResponse,
    CreateClusterRequest,
    CreateClusterResponse,
    CreateEnvironmentRequest,
    CreateEnvironmentResponse,
    EnvironmentHealthResponse,
    EnvironmentLogsResponse,
    EnvironmentResponse,
    OpenFuyaoIssueResponse,
    OpenFuyaoOverviewResponse,
)
from witty_service.domain.errors import DomainError
from witty_service.domain.openfuyao import ErrorCode

if TYPE_CHECKING:
    from witty_service.api.services import ServiceContainer
else:
    # FastAPI evaluates parameter annotations when it registers the routes.
    # The sidecar must not import api.services (and the full service
    # container) just to satisfy that lookup, so keep a cheap runtime alias.
    ServiceContainer = Any

router = APIRouter(
    prefix="/openfuyao",
    tags=["openfuyao"],
    dependencies=[Depends(require_bearer_auth)],
)


def get_services(request: Request) -> ServiceContainer:
    return request.app.state.services


@router.post("/environments", response_model=CreateEnvironmentResponse)
async def create_environment(
    payload: CreateEnvironmentRequest,
    response: Response,
    services: ServiceContainer = Depends(get_services),
) -> CreateEnvironmentResponse:
    result = await services.get_openfuyao_service().create_environment(
        agent_id=payload.agent_id, dry_run=payload.dry_run
    )
    response.status_code = (
        status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    )
    return CreateEnvironmentResponse(
        environment=(
            EnvironmentResponse.from_record(result.environment)
            if result.environment is not None
            else None
        ),
        preflight=result.preflight.to_dict(),
        plan=[dict(step) for step in result.plan],
        created=result.created,
    )


@router.get("/environments", response_model=list[EnvironmentResponse])
def list_environments(
    agent_id: str | None = Query(default=None),
    services: ServiceContainer = Depends(get_services),
) -> list[EnvironmentResponse]:
    records = services.get_openfuyao_service().list_environments(agent_id=agent_id)
    return [EnvironmentResponse.from_record(record) for record in records]


@router.get("/environments/{environment_id}", response_model=EnvironmentResponse)
def get_environment(
    environment_id: str,
    agent_id: str | None = Query(default=None),
    services: ServiceContainer = Depends(get_services),
) -> EnvironmentResponse:
    record = services.get_openfuyao_service().get_environment(
        environment_id, agent_id=agent_id
    )
    return EnvironmentResponse.from_record(record)


@router.post(
    "/environments/{environment_id}/bootstrap",
    response_model=EnvironmentResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def bootstrap_environment(
    environment_id: str,
    payload: BootstrapRequest,
    services: ServiceContainer = Depends(get_services),
) -> EnvironmentResponse:
    record = await services.get_openfuyao_service().bootstrap(
        environment_id, confirm=payload.confirm
    )
    return EnvironmentResponse.from_record(record)


@router.post(
    "/environments/{environment_id}/cancel",
    response_model=EnvironmentResponse,
)
async def cancel_environment(
    environment_id: str,
    services: ServiceContainer = Depends(get_services),
) -> EnvironmentResponse:
    record = await services.get_openfuyao_service().cancel(environment_id)
    return EnvironmentResponse.from_record(record)


@router.post(
    "/environments/{environment_id}/preflight",
    response_model=EnvironmentResponse,
)
async def recheck_environment_preflight(
    environment_id: str,
    agent_id: str | None = Query(default=None),
    services: ServiceContainer = Depends(get_services),
) -> EnvironmentResponse:
    """只重跑环境预检并刷新报告，不触发 Bootstrap。

    面板“重新预检”用：用户改完宿主机环境后想再确认一次，但暂时不部署。
    预检不通过时仍返回 200 + 更新后的报告（status=failed），
    让面板把哪一项没过直接摆出来，而不是弹一个错误再让人自己找。
    """
    record = await services.get_openfuyao_service().recheck_preflight(
        environment_id, agent_id=agent_id
    )
    return EnvironmentResponse.from_record(record)


@router.get(
    "/environments/{environment_id}/logs",
    response_model=EnvironmentLogsResponse,
)
def read_environment_logs(
    environment_id: str,
    cursor: int = Query(default=0, ge=0),
    limit_bytes: int = Query(default=64 * 1024, ge=1024, le=1024 * 1024),
    services: ServiceContainer = Depends(get_services),
) -> EnvironmentLogsResponse:
    page = services.get_openfuyao_service().read_logs(
        environment_id, cursor=cursor, limit_bytes=limit_bytes
    )
    return EnvironmentLogsResponse(**page.to_dict())


@router.post(
    "/environments/{environment_id}/health",
    response_model=EnvironmentHealthResponse,
)
async def check_environment_health(
    environment_id: str,
    services: ServiceContainer = Depends(get_services),
) -> EnvironmentHealthResponse:
    service = services.get_openfuyao_service()
    record = service.get_environment(environment_id)
    health = await service.health(environment_id)
    return EnvironmentHealthResponse(**health.to_dict(), proxy_url=record.proxy_url)


@router.get("/overview", response_model=OpenFuyaoOverviewResponse)
async def openfuyao_overview(
    agent_id: str = Query(min_length=1),
    services: ServiceContainer = Depends(get_services),
) -> OpenFuyaoOverviewResponse:
    """感知控制台侧变化：BKE 集群、Helm 应用、Pod 异常，并纳管到本服务。"""
    observed = await services.get_openfuyao_observer().refresh(agent_id)
    guide = observed.guide_console
    return OpenFuyaoOverviewResponse(
        clusters=[
            ClusterResponse.from_record(
                record, list(services.get_cluster_service().nodes(record.id))
            ).model_copy(update={"preflight": None})
            for record in observed.clusters
        ],
        apps=[AppResponse.from_record(record) for record in observed.apps],
        issues=[OpenFuyaoIssueResponse(**issue.to_dict()) for issue in observed.issues],
        console=ClusterConsoleResponse(
            available=observed.console.url is not None,
            url=observed.console.url,
            reason=observed.console.reason,
        ),
        guide_console=(
            ConsoleSessionProbeResponse(
                url=guide.console_url,
                reachable=guide.reachable,
                session_capable=guide.session_capable,
                reason=guide.reason,
            )
            if guide is not None
            else None
        ),
        refreshed_at=observed.refreshed_at,
        discovered=observed.discovered,
        errors=list(observed.errors),
    )


# ==============================================================================
# 阶段 2：集群
# ==============================================================================


def _cluster_response(services: ServiceContainer, cluster_id: str, name: str) -> Any:
    service = services.get_cluster_service()
    record = service.get_cluster(cluster_id)
    return ClusterResponse.from_record(record, list(service.nodes(record.id)))


@router.post("/clusters/preflight", response_model=ClusterPreflightResponse)
async def cluster_preflight(
    payload: ClusterPreflightRequest,
    services: ServiceContainer = Depends(get_services),
) -> ClusterPreflightResponse:
    result = await services.get_cluster_service().preflight(
        agent_id=payload.agent_id,
        raw_nodes=[node.model_dump() for node in payload.nodes],
        name=payload.name,
    )
    return ClusterPreflightResponse(
        ready=result.ready,
        summary=result.summary,
        failures=[
            ClusterPreflightFailureResponse(**item.to_dict())
            for item in result.failures
        ],
        tolerated=[
            ClusterPreflightFailureResponse(**item.to_dict())
            for item in result.tolerated
        ],
        preflight=result.payload,
    )


@router.post("/clusters", response_model=CreateClusterResponse)
async def create_cluster(
    payload: CreateClusterRequest,
    services: ServiceContainer = Depends(get_services),
) -> CreateClusterResponse:
    """阶段 2 已收口到控制台；API 保留路径但不再接受创建请求。"""
    del payload, services
    raise DomainError(
        code=ErrorCode.CLUSTER_CREATE_DISABLED,
        message=(
            "阶段 2 已改为在引导节点控制台手动创建业务集群；"
            "PolyMind 只负责感知、诊断和应用安装。"
        ),
        status_code=409,
    )


@router.get("/clusters", response_model=list[ClusterResponse])
def list_clusters(
    agent_id: str | None = Query(default=None),
    services: ServiceContainer = Depends(get_services),
) -> list[ClusterResponse]:
    service = services.get_cluster_service()
    return [
        ClusterResponse.from_record(record, list(service.nodes(record.id)))
        for record in service.list_clusters(agent_id=agent_id)
    ]


@router.get("/clusters/{cluster_id}", response_model=ClusterResponse)
def get_cluster(
    cluster_id: str,
    services: ServiceContainer = Depends(get_services),
) -> ClusterResponse:
    service = services.get_cluster_service()
    record = service.get_cluster(cluster_id)
    return ClusterResponse.from_record(record, list(service.nodes(record.id)))


@router.get("/clusters/{cluster_id}/console", response_model=ClusterConsoleResponse)
async def cluster_console(
    cluster_id: str,
    services: ServiceContainer = Depends(get_services),
) -> ClusterConsoleResponse:
    endpoint = await services.get_cluster_service().business_console(cluster_id)
    return ClusterConsoleResponse(
        available=endpoint.url is not None,
        url=endpoint.url,
        reason=endpoint.reason,
    )


@router.post("/clusters/{cluster_id}/cancel", response_model=ClusterResponse)
async def cancel_cluster(
    cluster_id: str,
    services: ServiceContainer = Depends(get_services),
) -> ClusterResponse:
    service = services.get_cluster_service()
    record = await service.cancel(cluster_id)
    return ClusterResponse.from_record(record, list(service.nodes(record.id)))


@router.delete("/clusters/{cluster_id}")
async def destroy_cluster(
    cluster_id: str,
    confirm: bool = Query(default=False),
    services: ServiceContainer = Depends(get_services),
) -> dict[str, Any]:
    record, nodes = await services.get_cluster_service().destroy(
        cluster_id, confirm=confirm
    )
    return {
        "destroyed": record.name,
        "nodes_dirty": [
            {
                "ip": node.ip,
                "hostname": node.hostname,
                "role": node.role,
                "note": "CR 已删除；节点上的 kubelet/控制面/容器仍可能残留，需重装或手工清理",
            }
            for node in nodes
        ],
    }


@router.get("/clusters/{cluster_id}/logs", response_model=EnvironmentLogsResponse)
def read_cluster_logs(
    cluster_id: str,
    cursor: int = Query(default=0, ge=0),
    limit_bytes: int = Query(default=64 * 1024, ge=1024, le=1024 * 1024),
    services: ServiceContainer = Depends(get_services),
) -> EnvironmentLogsResponse:
    page = services.get_cluster_service().read_logs(
        cluster_id, cursor=cursor, limit_bytes=limit_bytes
    )
    return EnvironmentLogsResponse(**page.to_dict())


# ==============================================================================
# 阶段 3：应用
# ==============================================================================


@router.post("/apps/preflight", response_model=AppPreflightResponse)
async def preflight_app(
    payload: AppPreflightRequest,
    services: ServiceContainer = Depends(get_services),
) -> AppPreflightResponse:
    result = await services.get_app_service().preflight(
        agent_id=payload.agent_id,
        cluster_name=payload.cluster,
        release_name=payload.release_name,
        namespace=payload.namespace,
        chart_dir=payload.chart_dir,
        repo_url=payload.repo_url,
        chart=payload.chart,
        chart_version=payload.chart_version,
        image=payload.image,
        node_port=payload.node_port,
    )
    return AppPreflightResponse(
        ready=result.ready,
        summary=result.summary,
        checks=[AppPreflightCheckResponse(**item.to_dict()) for item in result.checks],
    )


@router.post("/apps", response_model=CreateAppResponse)
async def install_app(
    payload: AppInstallRequest,
    response: Response,
    services: ServiceContainer = Depends(get_services),
) -> CreateAppResponse:
    result = await services.get_app_service().install(
        agent_id=payload.agent_id,
        cluster_name=payload.cluster,
        release_name=payload.release_name,
        namespace=payload.namespace,
        chart_dir=payload.chart_dir,
        repo_url=payload.repo_url,
        chart=payload.chart,
        chart_version=payload.chart_version,
        values=payload.values,
        image=payload.image,
        node_port=payload.node_port,
        verify_url=payload.verify_url,
        confirm=payload.confirm,
    )
    response.status_code = (
        status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    )
    return CreateAppResponse(
        app=AppResponse.from_record(result.app) if result.app is not None else None,
        created=result.created,
        needs_confirm=result.needs_confirm,
    )


@router.get("/apps", response_model=list[AppResponse])
def list_apps(
    cluster_id: str | None = Query(default=None),
    agent_id: str | None = Query(default=None),
    services: ServiceContainer = Depends(get_services),
) -> list[AppResponse]:
    records = services.get_app_service().list_apps(
        cluster_id=cluster_id, agent_id=agent_id
    )
    return [AppResponse.from_record(record) for record in records]


@router.post("/apps/{app_id}/rollback", response_model=AppResponse)
async def rollback_app(
    app_id: str,
    revision: int | None = Query(default=None, ge=1),
    confirm: bool = Query(default=False),
    services: ServiceContainer = Depends(get_services),
) -> AppResponse:
    return AppResponse.from_record(
        await services.get_app_service().rollback(
            app_id, revision=revision, confirm=confirm
        )
    )


@router.delete("/apps/{app_id}")
async def uninstall_app(
    app_id: str,
    confirm: bool = Query(default=False),
    services: ServiceContainer = Depends(get_services),
) -> dict[str, Any]:
    app = await services.get_app_service().uninstall(app_id, confirm=confirm)
    return {"uninstalled": app.release_name, "namespace": app.namespace}


@router.get("/apps/{app_id}", response_model=AppResponse)
def get_app(
    app_id: str,
    services: ServiceContainer = Depends(get_services),
) -> AppResponse:
    return AppResponse.from_record(services.get_app_service().get_app(app_id))


@router.post("/apps/{app_id}/cancel", response_model=AppResponse)
async def cancel_app(
    app_id: str,
    services: ServiceContainer = Depends(get_services),
) -> AppResponse:
    return AppResponse.from_record(await services.get_app_service().cancel(app_id))


@router.get("/apps/{app_id}/logs", response_model=EnvironmentLogsResponse)
def read_app_logs(
    app_id: str,
    cursor: int = Query(default=0, ge=0),
    limit_bytes: int = Query(default=64 * 1024, ge=1024, le=1024 * 1024),
    services: ServiceContainer = Depends(get_services),
) -> EnvironmentLogsResponse:
    page = services.get_app_service().read_logs(
        app_id, cursor=cursor, limit_bytes=limit_bytes
    )
    return EnvironmentLogsResponse(**page.to_dict())
