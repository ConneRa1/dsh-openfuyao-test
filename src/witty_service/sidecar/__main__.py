"""Process entrypoint for the openFuyao sidecar."""

from __future__ import annotations

import ctypes
import logging
import os
import signal
import socket
import sys
import threading
import time
from collections.abc import Sequence

from witty_service.sidecar.config import SidecarConfig

logger = logging.getLogger(__name__)


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _bind(host: str, port: int) -> socket.socket:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(128)
    return sock


def _set_parent_death_signal() -> bool:
    """Ask Linux to SIGTERM this process when its parent dies."""
    if not sys.platform.startswith("linux"):
        return False
    try:
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        return bool(libc.prctl(1, signal.SIGTERM) == 0)  # PR_SET_PDEATHSIG
    except (OSError, AttributeError):
        return False


def _watch_parent(parent_pid: int) -> None:
    """Fallback for platforms without PR_SET_PDEATHSIG."""
    while True:
        time.sleep(5.0)
        try:
            os.kill(parent_pid, 0)
        except ProcessLookupError:
            logger.warning("Parent process %d is gone; stopping sidecar", parent_pid)
            os._exit(0)
        except PermissionError:
            continue


def _exit_if_parent_gone(parent_pid: int) -> None:
    if parent_pid <= 0:
        return
    if _set_parent_death_signal():
        # PR_SET_PDEATHSIG only covers a death that happens after it is set.
        # The parent may have exited in between, in which case the signal never
        # fires and this process would live on as an orphan.
        if os.getppid() != parent_pid:
            logger.warning("Parent process %d is gone; stopping sidecar", parent_pid)
            raise SystemExit(0)
        return
    threading.Thread(
        target=_watch_parent,
        args=(parent_pid,),
        name="sidecar-parent-watchdog",
        daemon=True,
    ).start()


def _serve(config: SidecarConfig) -> None:
    config.apply_environment()

    # Import after the environment is configured: get_settings() is a
    # process-wide singleton, and the API/services import the config module.
    from witty_service.sidecar.app import create_sidecar_app
    from witty_service.sidecar.services import SidecarServices

    services = SidecarServices(config)
    sock = _bind(config.host, config.port)
    port = int(sock.getsockname()[1])
    _exit_if_parent_gone(config.parent_pid)

    import uvicorn

    app = create_sidecar_app(services, config=config, port=port)
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=config.host,
            port=port,
            log_level=config.log_level.lower(),
            access_log=False,
            server_header=False,
        )
    )
    try:
        server.run(sockets=[sock])
    finally:
        sock.close()


def main(argv: Sequence[str] | None = None) -> int:
    config = SidecarConfig.from_args(argv)
    _configure_logging(config.log_level)
    try:
        _serve(config)
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
