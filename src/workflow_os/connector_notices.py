from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import MutableMapping

from workflow_os.connector_state import AuthMethod, ConnectorHealth, ConnectorState


IMPORTANT_HEALTH = {
    ConnectorHealth.INVALID_AUTH,
    ConnectorHealth.DEPRECATED,
    ConnectorHealth.UNREACHABLE,
}


@dataclass(frozen=True)
class ConnectorRequirement:
    expected_auth_method: AuthMethod | None = None
    minimum_version: str | None = None


@dataclass(frozen=True)
class ConnectorNotice:
    notice_id: str
    connector_id: str
    code: str
    message: str
    settings_anchor: str
    important: bool = True


class ConnectorNoticeStore:
    """Persistent, secret-free dismissal state for Captain connector notices."""

    def __init__(
        self,
        backend: MutableMapping[str, str] | None = None,
        reminder_interval: timedelta = timedelta(hours=24),
    ) -> None:
        self._backend = backend if backend is not None else {}
        self._reminder_interval = reminder_interval

    def dismiss(self, notice: ConnectorNotice, *, now: datetime | None = None) -> None:
        now = now or datetime.now(timezone.utc)
        self._backend[self._dismissal_key(notice)] = (
            now + self._reminder_interval
        ).isoformat()

    def is_dismissed(self, notice: ConnectorNotice, *, now: datetime | None = None) -> bool:
        raw = self._backend.get(self._dismissal_key(notice))
        if not raw:
            return False
        try:
            until = datetime.fromisoformat(raw)
        except ValueError:
            return False
        now = now or datetime.now(timezone.utc)
        return until > now

    def clear_resolved(self, active_notices: list[ConnectorNotice]) -> None:
        active = {self._dismissal_key(n) for n in active_notices}
        for key in list(self._backend):
            if key.startswith("connector_notice:") and key not in active:
                del self._backend[key]

    @staticmethod
    def _dismissal_key(notice: ConnectorNotice) -> str:
        return f"connector_notice:{notice.connector_id}:{notice.code}"


def build_connector_notices(
    state: ConnectorState,
    requirement: ConnectorRequirement | None = None,
) -> list[ConnectorNotice]:
    """Return actionable Settings notices without exposing auth material."""
    req = requirement or ConnectorRequirement()
    notices: list[ConnectorNotice] = []
    anchor = f"/settings/connectors/{state.connector_id}"

    def add(code: str, message: str, important: bool = True) -> None:
        notices.append(ConnectorNotice(
            notice_id=f"{state.connector_id}:{code}",
            connector_id=state.connector_id,
            code=code,
            message=message,
            settings_anchor=anchor,
            important=important,
        ))

    if not state.installed:
        add("not_installed", "Connector is not installed.")
        return notices
    if not state.connected:
        add("not_connected", "Connector is not connected. Open Settings to connect.")
    if state.connected and not state.enabled:
        add("disabled", "Connector is connected but disabled.", important=False)
    if not state.permissions_ready:
        add("permissions", "Connector is missing required permissions.")

    if state.health is ConnectorHealth.INVALID_AUTH:
        add("invalid_auth", "Connector authentication is invalid or expired.")
    elif state.health is ConnectorHealth.DEPRECATED:
        add("deprecated", "Connector or provider setup is deprecated and needs migration.")
    elif state.health is ConnectorHealth.UNREACHABLE:
        add("unreachable", "Connector provider is currently unreachable.")
    elif state.health is ConnectorHealth.DEGRADED:
        add("degraded", "Connector health is degraded.", important=False)

    if req.expected_auth_method and state.auth_method is not req.expected_auth_method:
        add(
            "auth_method_migration",
            f"Connector now requires {req.expected_auth_method.value} authentication.",
        )
    if req.minimum_version and state.version and _version_lt(state.version, req.minimum_version):
        add("version", f"Connector must be upgraded to at least {req.minimum_version}.")

    return notices


def visible_connector_notices(
    notices: list[ConnectorNotice],
    store: ConnectorNoticeStore,
    *,
    now: datetime | None = None,
) -> list[ConnectorNotice]:
    return [n for n in notices if not store.is_dismissed(n, now=now)]


def _version_lt(current: str, minimum: str) -> bool:
    def parts(value: str) -> tuple[int, ...]:
        try:
            return tuple(int(p) for p in value.strip().lstrip("v").split("."))
        except ValueError:
            return ()
    a, b = parts(current), parts(minimum)
    return bool(a and b and a < b)
