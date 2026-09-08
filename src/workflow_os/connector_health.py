from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Mapping

from workflow_os.connector_state import ConnectorHealth, ConnectorState


class ConnectionTestCode(str, Enum):
    OK = "ok"
    INVALID_AUTH = "invalid_auth"
    UNREACHABLE = "unreachable"
    DEGRADED = "degraded"
    DEPRECATED = "deprecated"
    ERROR = "error"


@dataclass(frozen=True)
class ConnectionTestResult:
    connector_id: str
    code: ConnectionTestCode
    checked_at: datetime
    provider_version: str | None = None
    message: str | None = None

    @property
    def health(self) -> ConnectorHealth:
        return {
            ConnectionTestCode.OK: ConnectorHealth.HEALTHY,
            ConnectionTestCode.INVALID_AUTH: ConnectorHealth.INVALID_AUTH,
            ConnectionTestCode.UNREACHABLE: ConnectorHealth.UNREACHABLE,
            ConnectionTestCode.DEGRADED: ConnectorHealth.DEGRADED,
            ConnectionTestCode.DEPRECATED: ConnectorHealth.DEPRECATED,
            ConnectionTestCode.ERROR: ConnectorHealth.UNKNOWN,
        }[self.code]

    def public_status(self) -> dict[str, object]:
        return {
            "connector_id": self.connector_id,
            "code": self.code.value,
            "health": self.health.value,
            "checked_at": self.checked_at.isoformat(),
            "provider_version": self.provider_version,
            "message": self.message,
        }


ProviderProbe = Callable[[], Mapping[str, object]]
def test_connection(
    state: ConnectorState,
    probe: ProviderProbe,
    *,
    now: datetime | None = None,
) -> ConnectionTestResult:
    """Run an explicit provider probe and map it to secret-free Captain state."""
    if not state.installed:
        return _result(state, ConnectionTestCode.ERROR, now, "Connector is not installed.")
    if not state.connected:
        return _result(state, ConnectionTestCode.ERROR, now, "Connector is not connected.")

    try:
        raw = dict(probe())
    except Exception:
        return _result(state, ConnectionTestCode.ERROR, now, "Connection test failed.")

    code = _parse_code(raw.get("code"))
    version = raw.get("provider_version")
    message = raw.get("message")
    return ConnectionTestResult(
        connector_id=state.connector_id,
        code=code,
        checked_at=now or datetime.now(timezone.utc),
        provider_version=version if isinstance(version, str) else None,
        message=_sanitize_public_text(message) if isinstance(message, str) else None,
    )


def _sanitize_public_text(value: str, *, limit: int = 240) -> str:
    text = value.replace("\r", " ").replace("\n", " ").strip()
    lowered = text.lower()
    markers = ("token", "secret", "api_key", "apikey", "authorization", "bearer ")
    if any(marker in lowered for marker in markers):
        return "[redacted]"
    return text[:limit]


def _parse_code(value: object) -> ConnectionTestCode:
    if isinstance(value, ConnectionTestCode):
        return value
    if isinstance(value, str):
        try:
            return ConnectionTestCode(value)
        except ValueError:
            return ConnectionTestCode.ERROR
    return ConnectionTestCode.ERROR


def _result(
    state: ConnectorState,
    code: ConnectionTestCode,
    now: datetime | None,
    message: str,
) -> ConnectionTestResult:
    return ConnectionTestResult(
        connector_id=state.connector_id,
        code=code,
        checked_at=now or datetime.now(timezone.utc),
        message=message,
    )
