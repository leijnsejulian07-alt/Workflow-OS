from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from workflow_os.connector_notices import (
    ConnectorNoticeStore,
    ConnectorRequirement,
    build_connector_notices,
    visible_connector_notices,
)
from workflow_os.connector_state import ConnectorState
from workflow_os.project_scope import ScopedAccessContext, ScopedResourceRef


@dataclass(frozen=True)
class ConnectorControlCenterSnapshot:
    """Secret-free, scope-bound connector projection for Captain's Control Center."""

    connector_id: str
    installed: bool
    connected: bool
    enabled: bool
    ready: bool
    permissions_ready: bool
    auth_method: str
    health: str
    version: str | None
    notices: tuple[dict[str, object], ...]
    scope_ref: ScopedResourceRef

    def require_context(self, context: ScopedAccessContext) -> None:
        self.scope_ref.require_context(context)

    def as_public_dict(self, *, context: ScopedAccessContext) -> dict[str, object]:
        self.require_context(context)
        return {
            "connector_id": self.connector_id,
            "installed": self.installed,
            "connected": self.connected,
            "enabled": self.enabled,
            "ready": self.ready,
            "permissions_ready": self.permissions_ready,
            "auth_method": self.auth_method,
            "health": self.health,
            "version": self.version,
            "notices": [dict(item) for item in self.notices],
        }


def build_connector_control_center_snapshot(
    state: ConnectorState,
    *,
    context: ScopedAccessContext,
    notice_store: ConnectorNoticeStore,
    requirement: ConnectorRequirement | None = None,
    now: datetime | None = None,
) -> ConnectorControlCenterSnapshot:
    """Derive Control Center state from canonical Settings state; never cache authority."""
    if not isinstance(context, ScopedAccessContext):
        raise ValueError("explicit ScopedAccessContext required")
    if not isinstance(notice_store, ConnectorNoticeStore):
        raise ValueError("explicit ConnectorNoticeStore required")

    notices = build_connector_notices(
        state,
        context=context,
        requirement=requirement,
    )
    visible = visible_connector_notices(
        notices,
        notice_store,
        context=context,
        now=now,
    )
    notice_store.clear_resolved(notices, context=context)

    public_notices = tuple(
        {
            "notice_id": notice.notice_id,
            "code": notice.code,
            "message": notice.message,
            "important": notice.important,
            "settings_anchor": notice.settings_anchor,
        }
        for notice in visible
    )
    return ConnectorControlCenterSnapshot(
        connector_id=state.connector_id,
        installed=state.installed,
        connected=state.connected,
        enabled=state.enabled,
        ready=state.ready,
        permissions_ready=state.permissions_ready,
        auth_method=state.auth_method.value,
        health=state.health.value,
        version=state.version,
        notices=public_notices,
        scope_ref=ScopedResourceRef.bind(
            context=context,
            resource_kind="connector_snapshot",
            resource_id=state.connector_id,
        ),
    )
