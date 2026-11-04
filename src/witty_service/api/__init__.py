"""HTTP API package.

Exports are resolved lazily: importing a single router (for example the
openFuyao sidecar) must not pull the full service container and its optional
runtime dependencies into the process.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__all__ = ["ServiceContainer", "build_default_services", "require_bearer_auth"]

if TYPE_CHECKING:
    from witty_service.api.auth import require_bearer_auth
    from witty_service.api.services import ServiceContainer, build_default_services


def __getattr__(name: str) -> Any:
    if name == "require_bearer_auth":
        from witty_service.api.auth import require_bearer_auth

        return require_bearer_auth
    if name in {"ServiceContainer", "build_default_services"}:
        from witty_service.api.services import (
            ServiceContainer,
            build_default_services,
        )

        return {
            "ServiceContainer": ServiceContainer,
            "build_default_services": build_default_services,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
