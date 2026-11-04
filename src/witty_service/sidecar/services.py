"""The minimal service graph used by the openFuyao sidecar.

It wires only the four getters consumed by ``api/openfuyao.py``. The original
services, repositories, state machines, and runners are reused unchanged.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from witty_service.application.openfuyao.app_service import AppService
from witty_service.application.openfuyao.cluster_service import ClusterService
from witty_service.application.openfuyao.environment_service import EnvironmentService
from witty_service.application.openfuyao.overview import OpenFuyaoObserver
from witty_service.config import get_settings
from witty_service.persistence.db import (
    create_session_factory,
    create_sqlite_engine,
    init_db,
)
from witty_service.persistence.openfuyao_cluster_repository import (
    OpenFuyaoClusterRepository,
)
from witty_service.persistence.openfuyao_repository import OpenFuyaoRepository
from witty_service.persistence.orm import AgentORM
from witty_service.sidecar.config import SidecarConfig

logger = logging.getLogger(__name__)


class EphemeralAgent:
    """Stand-in for an agent id that has no database row yet.

    ``EnvironmentService`` only asks whether an agent exists before recording
    the environment. A fresh sidecar database has no agents, so the plugin's
    fixed pseudo-agent is accepted here; a database copied from a real
    deployment keeps validating real agent ids.
    """

    __slots__ = ("id",)

    def __init__(self, agent_id: str) -> None:
        self.id = agent_id


class SidecarAgentLookup:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        allow_ephemeral: bool,
        ephemeral_agent_id: str,
    ) -> None:
        self._session_factory = session_factory
        self._allow_ephemeral = allow_ephemeral
        self._ephemeral_agent_id = ephemeral_agent_id
        self._warned = False

    def get_agent(self, agent_id: str) -> Any | None:
        with self._session_factory() as session:
            row = session.get(AgentORM, agent_id)
        if row is not None:
            return row
        if not self._allow_ephemeral or agent_id != self._ephemeral_agent_id:
            return None
        if not self._warned:
            self._warned = True
            logger.warning(
                "openFuyao sidecar accepts configured ephemeral agent id %r "
                "(no agent row)",
                agent_id,
            )
        return EphemeralAgent(agent_id)


class SidecarServices:
    """Owns the sidecar database and the four openFuyao service instances."""

    def __init__(self, config: SidecarConfig) -> None:
        self._config = config
        self._engine = create_sqlite_engine(config.database_url)
        init_db(self._engine, auto_create=True)
        self._session_factory = create_session_factory(self._engine)
        self._agent_lookup = SidecarAgentLookup(
            self._session_factory,
            allow_ephemeral=config.allow_ephemeral_agent,
            ephemeral_agent_id=config.agent_id,
        )
        self._openfuyao: EnvironmentService | None = None
        self._clusters: ClusterService | None = None
        self._apps: AppService | None = None
        self._observer: OpenFuyaoObserver | None = None
        logger.info(
            "Sidecar database ready: %s (workspace=%s)",
            config.db_path,
            config.workspace_root,
        )

    @property
    def session_factory(self) -> sessionmaker[Session]:
        return self._session_factory

    def _workspace_root(self) -> Path:
        return self._config.workspace_root

    def get_openfuyao_service(self) -> EnvironmentService:
        if self._openfuyao is None:
            self._openfuyao = EnvironmentService(
                repository=OpenFuyaoRepository(self._session_factory),
                agent_repository=self._agent_lookup,
                settings=get_settings().openfuyao,
                workspace_root=self._workspace_root(),
            )
        return self._openfuyao

    def get_cluster_service(self) -> ClusterService:
        if self._clusters is None:
            self._clusters = ClusterService(
                repository=OpenFuyaoClusterRepository(self._session_factory),
                environment_repository=OpenFuyaoRepository(self._session_factory),
                settings=get_settings().openfuyao,
                workspace_root=self._workspace_root(),
            )
        return self._clusters

    def get_app_service(self) -> AppService:
        if self._apps is None:
            self._apps = AppService(
                repository=OpenFuyaoClusterRepository(self._session_factory),
                settings=get_settings().openfuyao,
                workspace_root=self._workspace_root(),
            )
        return self._apps

    def get_openfuyao_observer(self) -> OpenFuyaoObserver:
        if self._observer is None:
            self._observer = OpenFuyaoObserver(
                repository=OpenFuyaoClusterRepository(self._session_factory),
                environment_repository=OpenFuyaoRepository(self._session_factory),
                settings=get_settings().openfuyao,
                workspace_root=self._workspace_root(),
            )
        return self._observer

    def recover_stale(self) -> dict[str, int]:
        """Mark work interrupted by a previous sidecar process as failed."""
        counts = {
            "environments": self.get_openfuyao_service().recover_stale(),
            "clusters": self.get_cluster_service().recover_stale(),
            "apps": self.get_app_service().recover_stale(),
        }
        if any(counts.values()):
            logger.warning("Recovered interrupted openFuyao work: %s", counts)
        return counts

    async def close(self) -> None:
        for service in (self._openfuyao, self._clusters, self._apps):
            if service is None:
                continue
            try:
                await service.close()
            except Exception:
                logger.exception("Failed to close sidecar service")
        self._engine.dispose()
