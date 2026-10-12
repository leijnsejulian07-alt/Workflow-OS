from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, MutableMapping

from .project_scope import ScopedAccessContext, ScopeMismatchError


class ProjectMemoryError(RuntimeError):
    """Raised for invalid or corrupt Captain memory state."""


@dataclass(frozen=True)
class _StoredProjectMemory:
    scope_digest: str
    state_epoch: int
    value: Any


class ProjectMemoryStore:
    """Fail-closed memory adapter with explicit project, normal-chat, and global lanes."""

    def __init__(self, backend: MutableMapping[str, Any] | None = None) -> None:
        self._backend: MutableMapping[str, Any] = backend if backend is not None else {}

    @staticmethod
    def _require_context(context: ScopedAccessContext) -> ScopedAccessContext:
        if not isinstance(context, ScopedAccessContext):
            raise ScopeMismatchError("explicit ScopedAccessContext required for project memory")
        return context

    @staticmethod
    def _clean_key(key: str) -> str:
        if not isinstance(key, str) or not key or len(key) > 256 or "\0" in key:
            raise ValueError("invalid memory key")
        return key

    @classmethod
    def _project_key(cls, context: ScopedAccessContext, key: str) -> str:
        context = cls._require_context(context)
        return f"project:{context.scope.digest}:{context.state_epoch}:{cls._clean_key(key)}"

    @classmethod
    def _chat_key(cls, chat_id: str, key: str) -> str:
        if not isinstance(chat_id, str) or not chat_id or len(chat_id) > 128 or "\0" in chat_id:
            raise ValueError("invalid chat_id")
        return f"chat:{chat_id}:{cls._clean_key(key)}"

    @classmethod
    def _global_key(cls, key: str) -> str:
        return f"global:{cls._clean_key(key)}"

    def put_project(self, *, context: ScopedAccessContext, key: str, value: Any) -> None:
        context = self._require_context(context)
        self._backend[self._project_key(context, key)] = _StoredProjectMemory(
            scope_digest=context.scope.digest,
            state_epoch=context.state_epoch,
            value=deepcopy(value),
        )

    def get_project(self, *, context: ScopedAccessContext, key: str, default: Any = None) -> Any:
        context = self._require_context(context)
        stored = self._backend.get(self._project_key(context, key))
        if stored is None:
            return deepcopy(default)
        if not isinstance(stored, _StoredProjectMemory):
            raise ProjectMemoryError("corrupt project memory entry")
        if stored.scope_digest != context.scope.digest or stored.state_epoch != context.state_epoch:
            raise ProjectMemoryError("project memory binding mismatch")
        return deepcopy(stored.value)

    def delete_project(self, *, context: ScopedAccessContext, key: str) -> bool:
        context = self._require_context(context)
        storage_key = self._project_key(context, key)
        stored = self._backend.get(storage_key)
        if stored is None:
            return False
        if not isinstance(stored, _StoredProjectMemory):
            raise ProjectMemoryError("corrupt project memory entry")
        if stored.scope_digest != context.scope.digest or stored.state_epoch != context.state_epoch:
            raise ProjectMemoryError("project memory binding mismatch")
        del self._backend[storage_key]
        return True

    def put_chat(self, *, chat_id: str, key: str, value: Any) -> None:
        self._backend[self._chat_key(chat_id, key)] = deepcopy(value)

    def get_chat(self, *, chat_id: str, key: str, default: Any = None) -> Any:
        return deepcopy(self._backend.get(self._chat_key(chat_id, key), default))

    def put_global_distilled(self, *, key: str, value: Any, project_specific: bool) -> None:
        if project_specific is not False:
            raise PermissionError("project-specific learning may not enter global memory")
        self._backend[self._global_key(key)] = deepcopy(value)

    def get_global_distilled(self, *, key: str, default: Any = None) -> Any:
        return deepcopy(self._backend.get(self._global_key(key), default))
