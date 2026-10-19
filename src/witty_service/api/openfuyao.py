"""openFuyao Environment 端点。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response, status

from witty_service.api.auth import require_bearer_auth
from witty_service.api.openfuyao_schemas import (
    BootstrapRequest,
    CreateEnvironmentRequest,
    CreateEnvironmentResponse,
    EnvironmentHealthResponse,
    EnvironmentLogsResponse,
    EnvironmentResponse,
)
from witty_service.api.services import ServiceContainer

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
