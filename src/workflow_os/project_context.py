from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, MutableMapping

from .project_scope import ScopedAccessContext, ScopeMismatchError


class ProjectContextError(RuntimeError):
    """Raised for invalid or corrupt Captain project-context state."""


@dataclass(frozen=True)
class _StoredProjectContext:
    scope_digest: str
    state_epoch: int
    value: Any


class ProjectContextStore:
    """Fail-closed context-snapshot store bound to exact project scope and epoch."""

    def __init__(self, backend: MutableMapping[str, Any] | None = None) -> None:
        self._backend: MutableMapping[str, Any] = backend if backend is not None else {}

    @staticmethod
    def _require_context(context: ScopedAccessContext) -> ScopedAccessContext:
        if not isinstance(context, ScopedAccessContext):
            raise ScopeMismatchError("explicit ScopedAccessContext required for project context")
        return context

    @staticmethod
    def _clean_key(key: str) -> str:
        if not isinstance(key, str) or not key or len(key) > 256 or "\0" in key:
            raise ValueError("invalid context key")
        return key

    @classmethod
    def _storage_key(cls, context: ScopedAccessContext, key: str) -> str:
        context = cls._require_context(context)
        return f"context:{context.scope.digest}:{context.state_epoch}:{cls._clean_key(key)}"

    def put(self, *, context: ScopedAccessContext, key: str, value: Any) -> None:
        context = self._require_context(context)
        self._backend[self._storage_key(context, key)] = _StoredProjectContext(
            scope_digest=context.scope.digest,
            state_epoch=context.state_epoch,
            value=deepcopy(value),
        )

    def get(self, *, context: ScopedAccessContext, key: str, default: Any = None) -> Any:
        context = self._require_context(context)
        stored = self._backend.get(self._storage_key(context, key))
        if stored is None:
            return deepcopy(default)
        if not isinstance(stored, _StoredProjectContext):
            raise ProjectContextError("corrupt project context entry")
        if stored.scope_digest != context.scope.digest or stored.state_epoch != context.state_epoch:
            raise ProjectContextError("project context binding mismatch")
        return deepcopy(stored.value)

    def delete(self, *, context: ScopedAccessContext, key: str) -> bool:
        context = self._require_context(context)
        storage_key = self._storage_key(context, key)
        stored = self._backend.get(storage_key)
        if stored is None:
            return False
        if not isinstance(stored, _StoredProjectContext):
            raise ProjectContextError("corrupt project context entry")
        if stored.scope_digest != context.scope.digest or stored.state_epoch != context.state_epoch:
            raise ProjectContextError("project context binding mismatch")
        del self._backend[storage_key]
        return True
