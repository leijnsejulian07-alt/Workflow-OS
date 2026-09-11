from datetime import datetime, timezone

import pytest

from workflow_os.connector_control_center import build_connector_control_center_snapshot
from workflow_os.connector_notices import ConnectorNoticeStore
from workflow_os.connector_state import AuthMethod, ConnectorHealth, ConnectorState
from workflow_os.project_scope import ProjectScope, ScopeMismatchError, ScopedAccessContext


def ctx(chat: str, project: str, repo: str, epoch: int) -> ScopedAccessContext:
    return ScopedAccessContext(ProjectScope(chat, project, repo), epoch)


def test_snapshot_is_scope_bound_and_secret_free() -> None:
    context = ctx("chat-a", "project-a", "owner/repo-a", 7)
    state = ConnectorState(
        connector_id="github",
        installed=True,
        connected=True,
        enabled=True,
        auth_method=AuthMethod.OAUTH,
        health=ConnectorHealth.HEALTHY,
        required_permissions=frozenset({"repo:read"}),
        granted_permissions=frozenset({"repo:read"}),
        oauth_connection_ref="oauth-secret-reference",
        setup_url="https://provider.invalid/setup?token=secret-token",
        version="1.2.3",
    )
    snapshot = build_connector_control_center_snapshot(
        state,
        context=context,
        notice_store=ConnectorNoticeStore(),
    )
    public = snapshot.as_public_dict(context=context)

    assert public["ready"] is True
    assert public["permissions_ready"] is True
    rendered = repr(public)
    assert "oauth-secret-reference" not in rendered
    assert "secret-token" not in rendered
    assert "setup_url" not in public

    with pytest.raises(ScopeMismatchError):
        snapshot.as_public_dict(
            context=ctx("chat-a", "project-b", "owner/repo-a", 7)
        )
    with pytest.raises(ScopeMismatchError):
        snapshot.as_public_dict(
            context=ctx("chat-a", "project-a", "owner/repo-a", 8)
        )


def test_snapshot_uses_scoped_dismissal_state() -> None:
    context_a = ctx("chat-a", "project-a", "owner/repo", 1)
    context_b = ctx("chat-a", "project-b", "owner/repo", 1)
    store = ConnectorNoticeStore()
    state = ConnectorState(
        connector_id="github",
        installed=True,
        required_permissions=frozenset({"repo:read"}),
    )
    now = datetime(2026, 9, 11, 20, 0, tzinfo=timezone.utc)

    first = build_connector_control_center_snapshot(
        state, context=context_a, notice_store=store, now=now
    )
    assert {n["code"] for n in first.notices} == {"not_connected", "permissions"}

    from workflow_os.connector_notices import build_connector_notices

    notice = build_connector_notices(state, context=context_a)[0]
    store.dismiss(notice, context=context_a, now=now)

    hidden = build_connector_control_center_snapshot(
        state, context=context_a, notice_store=store, now=now
    )
    assert "not_connected" not in {n["code"] for n in hidden.notices}

    isolated = build_connector_control_center_snapshot(
        state, context=context_b, notice_store=store, now=now
    )
    assert "not_connected" in {n["code"] for n in isolated.notices}

    next_epoch = build_connector_control_center_snapshot(
        state,
        context=ctx("chat-a", "project-a", "owner/repo", 2),
        notice_store=store,
        now=now,
    )
    assert "not_connected" in {n["code"] for n in next_epoch.notices}
