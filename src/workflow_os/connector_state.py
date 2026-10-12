from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import FrozenSet


class AuthMethod(str, Enum):
    NONE = "none"
    OAUTH = "oauth"
    API_KEY = "api_key"
    ID_BASED = "id_based"


class ConnectorHealth(str, Enum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    INVALID_AUTH = "invalid_auth"
    DEPRECATED = "deprecated"
    UNREACHABLE = "unreachable"


@dataclass(frozen=True)
class ConnectorState:
    """Canonical secret-free connector state for Captain Settings."""

    connector_id: str
    installed: bool = False
    connected: bool = False
    enabled: bool = False
    auth_method: AuthMethod = AuthMethod.NONE
    health: ConnectorHealth = ConnectorHealth.UNKNOWN
    required_permissions: FrozenSet[str] = field(default_factory=frozenset)
    granted_permissions: FrozenSet[str] = field(default_factory=frozenset)
    oauth_connection_ref: str | None = None
    version: str | None = None
    setup_url: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.connector_id, str) or not self.connector_id.strip():
            raise ValueError("connector_id is required")
        if self.auth_method is AuthMethod.OAUTH and self.connected and not self.oauth_connection_ref:
            raise ValueError(
                "OAuth connector cannot be connected without an official connection reference"
            )
        if not self.connected and self.enabled:
            raise ValueError("disconnected connector cannot be enabled")

    @property
    def permissions_ready(self) -> bool:
        return self.required_permissions.issubset(self.granted_permissions)

    @property
    def ready(self) -> bool:
        return (
            self.installed
            and self.connected
            and self.enabled
            and self.health is ConnectorHealth.HEALTHY
            and self.permissions_ready
        )

    def public_status(self) -> dict[str, object]:
        """Return the Settings projection without credentials or secrets."""
        return {
            "connector_id": self.connector_id,
            "installed": self.installed,
            "connected": self.connected,
            "enabled": self.enabled,
            "ready": self.ready,
            "auth_method": self.auth_method.value,
            "health": self.health.value,
            "required_permissions": sorted(self.required_permissions),
            "granted_permissions": sorted(self.granted_permissions),
            "permissions_ready": self.permissions_ready,
            "version": self.version,
            "setup_url": self.setup_url,
        }
