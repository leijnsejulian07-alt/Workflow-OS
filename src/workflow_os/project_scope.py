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
class ScopedResourceRef:
    resource_kind: str
    resource_id: str
    scope_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "resource_kind", _clean_id(self.resource_kind, "resource_kind"))
        object.__setattr__(self, "resource_id", _clean_id(self.resource_id, "resource_id"))
        if not isinstance(self.scope_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", self.scope_digest):
            raise ValueError("invalid scope_digest")

    @classmethod
    def bind(cls, *, scope: ProjectScope, resource_kind: str, resource_id: str) -> "ScopedResourceRef":
        return cls(resource_kind=resource_kind, resource_id=resource_id, scope_digest=scope.digest)

    def require_scope(self, scope: ProjectScope) -> None:
        if not isinstance(scope, ProjectScope):
            raise ScopeMismatchError("explicit ProjectScope required")
        if not hmac.compare_digest(self.scope_digest, scope.digest):
            raise ScopeMismatchError("resource belongs to a different Captain scope")
