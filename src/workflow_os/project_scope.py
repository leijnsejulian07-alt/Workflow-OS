from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import re

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_REPO_SCOPE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}/[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")


class ScopeMismatchError(PermissionError):
    """Raised when a resource is accessed outside its bound Captain scope."""


def _clean_id(value: str, field: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ValueError(f"invalid {field}")
    return value


def _clean_repo_scope(value: str) -> str:
    if not isinstance(value, str) or not _REPO_SCOPE_RE.fullmatch(value):
        raise ValueError("invalid repo_scope")
    return value


def _clean_epoch(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("invalid state_epoch")
    return value


@dataclass(frozen=True)
class ProjectScope:
    chat_id: str
    project_id: str
    repo_scope: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "chat_id", _clean_id(self.chat_id, "chat_id"))
        object.__setattr__(self, "project_id", _clean_id(self.project_id, "project_id"))
        object.__setattr__(self, "repo_scope", _clean_repo_scope(self.repo_scope))

    @property
    def digest(self) -> str:
        raw = "\0".join((self.chat_id, self.project_id, self.repo_scope)).encode()
        return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class ScopedAccessContext:
    """Current authoritative Captain scope plus its revocation epoch."""

    scope: ProjectScope
    state_epoch: int

    def __post_init__(self) -> None:
        if not isinstance(self.scope, ProjectScope):
            raise ValueError("explicit ProjectScope required")
        object.__setattr__(self, "state_epoch", _clean_epoch(self.state_epoch))


@dataclass(frozen=True)
class ScopedResourceRef:
    resource_kind: str
    resource_id: str
    scope_digest: str
    state_epoch: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "resource_kind", _clean_id(self.resource_kind, "resource_kind"))
        object.__setattr__(self, "resource_id", _clean_id(self.resource_id, "resource_id"))
        if not isinstance(self.scope_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", self.scope_digest):
            raise ValueError("invalid scope_digest")
        object.__setattr__(self, "state_epoch", _clean_epoch(self.state_epoch))

    @classmethod
    def bind(
        cls,
        *,
        context: ScopedAccessContext,
        resource_kind: str,
        resource_id: str,
    ) -> "ScopedResourceRef":
        if not isinstance(context, ScopedAccessContext):
            raise ValueError("explicit ScopedAccessContext required")
        return cls(
            resource_kind=resource_kind,
            resource_id=resource_id,
            scope_digest=context.scope.digest,
            state_epoch=context.state_epoch,
        )

    def require_context(self, context: ScopedAccessContext) -> None:
        if not isinstance(context, ScopedAccessContext):
            raise ScopeMismatchError("explicit ScopedAccessContext required")
        if not hmac.compare_digest(self.scope_digest, context.scope.digest):
            raise ScopeMismatchError("resource belongs to a different Captain scope")
        if self.state_epoch != context.state_epoch:
            raise ScopeMismatchError("resource belongs to a stale or future Project State epoch")
