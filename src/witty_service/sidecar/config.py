"""Configuration for the headless openFuyao sidecar.

The sidecar is a private child process started by the DSH plugin. It owns its
SQLite database and workspace, binds to loopback on an ephemeral port, and
requires a per-start bearer token passed through the environment (never argv).
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

#: Bumped when the plugin/sidecar contract changes.
SIDECAR_API_VERSION = 1
DEFAULT_AGENT_ID = "openfuyao-deployer"
_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise ValueError("must be positive")
    return number


@dataclass(frozen=True, slots=True)
class SidecarConfig:
    """Resolved sidecar startup configuration."""

    token: str
    db_path: Path
    workspace_root: Path
    host: str = "127.0.0.1"
    port: int = 0
    agent_id: str = DEFAULT_AGENT_ID
    allow_ephemeral_agent: bool = True
    parent_pid: int = 0
    log_level: str = "INFO"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    def apply_environment(self) -> None:
        """Export the settings the shared service layer reads.

        ``witty_service.config`` is environment-driven and has a process-wide
        singleton. The sidecar sets these values before the first
        ``get_settings()`` call so the original application code can run
        unchanged in a private process.
        """
        os.environ["AUTH_TOKEN"] = self.token
        os.environ["WITTY_DATABASE_URL"] = self.database_url
        os.environ["WITTY_DATABASE_AUTO_CREATE"] = "true"
        os.environ["WITTY_WORKSPACE_ROOT"] = str(self.workspace_root)
        os.environ["OPENFUYAO_WORK_DIR"] = str(self.workspace_root / "openfuyao")
        os.environ["WITTY_LOG_LEVEL"] = self.log_level

    @classmethod
    def from_args(cls, argv: Sequence[str] | None = None) -> SidecarConfig:
        parser = argparse.ArgumentParser(
            prog="witty-openfuyao-sidecar",
            description="Headless openFuyao orchestration sidecar",
        )
        parser.add_argument(
            "--token",
            default=os.getenv("WITTY_SIDECAR_TOKEN", ""),
            help="Bearer token clients must present (or WITTY_SIDECAR_TOKEN)",
        )
        parser.add_argument(
            "--db-path",
            default=os.getenv("WITTY_SIDECAR_DB", ""),
            help="SQLite database path (or WITTY_SIDECAR_DB)",
        )
        parser.add_argument(
            "--workspace",
            default=os.getenv("WITTY_SIDECAR_WORKSPACE", ""),
            help="Workspace root for openFuyao logs (or WITTY_SIDECAR_WORKSPACE)",
        )
        parser.add_argument(
            "--host",
            default=os.getenv("WITTY_SIDECAR_HOST", "127.0.0.1"),
        )
        parser.add_argument(
            "--port",
            type=int,
            default=int(os.getenv("WITTY_SIDECAR_PORT", "0")),
            help="TCP port; 0 selects a free loopback port",
        )
        parser.add_argument(
            "--agent-id",
            default=os.getenv("WITTY_SIDECAR_AGENT_ID", DEFAULT_AGENT_ID),
        )
        parser.add_argument(
            "--allow-ephemeral-agent",
            action=argparse.BooleanOptionalAction,
            default=_env_bool("WITTY_SIDECAR_ALLOW_EPHEMERAL_AGENT", True),
            help=(
                "Accept an agent id that has no row in the sidecar database "
                "(needed by a fresh plugin database)"
            ),
        )
        parser.add_argument(
            "--parent-pid",
            type=int,
            default=int(os.getenv("WITTY_SIDECAR_PARENT_PID", "0")),
            help="Exit when this process disappears",
        )
        parser.add_argument(
            "--log-level",
            choices=_LOG_LEVELS,
            default=os.getenv("WITTY_SIDECAR_LOG_LEVEL", "INFO").upper(),
        )
        args = parser.parse_args(argv)

        token = args.token.strip()
        if not token:
            parser.error("--token or WITTY_SIDECAR_TOKEN is required")
        if not args.db_path.strip():
            parser.error("--db-path or WITTY_SIDECAR_DB is required")
        if not args.workspace.strip():
            parser.error("--workspace or WITTY_SIDECAR_WORKSPACE is required")
        if not 0 <= args.port <= 65535:
            parser.error("--port must be between 0 and 65535")
        if args.parent_pid < 0:
            parser.error("--parent-pid must be >= 0")

        db_path = Path(args.db_path).expanduser().resolve()
        workspace_root = Path(args.workspace).expanduser().resolve()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        workspace_root.mkdir(parents=True, exist_ok=True)

        return cls(
            token=token,
            db_path=db_path,
            workspace_root=workspace_root,
            host=args.host,
            port=args.port,
            agent_id=args.agent_id.strip() or DEFAULT_AGENT_ID,
            allow_ephemeral_agent=args.allow_ephemeral_agent,
            parent_pid=args.parent_pid,
            log_level=args.log_level,
        )
