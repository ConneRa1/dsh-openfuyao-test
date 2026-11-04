"""Application layer package.

The original module re-exported agent/session managers eagerly. That made any
import below ``witty_service.application`` (including the openFuyao sidecar)
depend on sandbox, adapter, and model-runtime packages. Resolve each name from
its owning module on first access instead; ``__all__`` keeps the public surface
unchanged.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "AGENT_NOT_FOUND",
    "AGENT_NOT_RUNNING",
    "INVALID_AGENT_TRANSITION",
    "SANDBOX_STATE_NOT_FOUND",
    "SESSION_AGENT_MISMATCH",
    "SESSION_NOT_FOUND",
    "AgentCreateRequest",
    "AgentCreateResult",
    "AgentManager",
    "SessionManager",
]

_AGENT_MANAGER_EXPORTS = frozenset(
    {
        "AGENT_NOT_RUNNING",
        "INVALID_AGENT_TRANSITION",
        "SANDBOX_STATE_NOT_FOUND",
        "AgentCreateRequest",
        "AgentCreateResult",
        "AgentManager",
    }
)
_SESSION_MANAGER_EXPORTS = frozenset({"SESSION_AGENT_MISMATCH", "SessionManager"})
_DOMAIN_ERROR_EXPORTS = frozenset({"AGENT_NOT_FOUND", "SESSION_NOT_FOUND"})


def __getattr__(name: str) -> Any:
    if name in _AGENT_MANAGER_EXPORTS:
        module = import_module("witty_service.application.agent_manager")
        return getattr(module, name)
    if name in _SESSION_MANAGER_EXPORTS:
        module = import_module("witty_service.application.session_manager")
        return getattr(module, name)
    if name in _DOMAIN_ERROR_EXPORTS:
        module = import_module("witty_service.domain.errors")
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
