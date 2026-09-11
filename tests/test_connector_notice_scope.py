from datetime import datetime, timedelta, timezone

import pytest

from workflow_os.connector_notices import (
    ConnectorNoticeStore,
    build_connector_notices,
    visible_connector_notices,
)
from workflow_os.connector_state import ConnectorState
from workflow_os.project_scope import ProjectScope, ScopeMismatchError, ScopedAccessContext


def ctx(chat: str, project: str, repo: str, epoch: int = 1) -> ScopedAccessContext:
    return ScopedAccessContext(ProjectScope(chat, project, repo), epoch)


def disconnected() -> ConnectorState:
    return ConnectorState(connector_id="github", installed=True)


def test_dismissal_isolated_across_projects_and_epochs():
    store = ConnectorNoticeStore(reminder_interval=timedelta(hours=24))
    now = datetime(2026, 9, 11, 18, 0, tzinfo=timezone.utc)
    a = ctx("chat-a", "project-a", "owner/repo-a")
    b = ctx("chat-b", "project-b", "owner/repo-b")
    a2 = ctx("chat-a", "project-a", "owner/repo-a", epoch=2)

    notice_a = build_connector_notices(disconnected(), context=a)[0]
    notice_b = build_connector_notices(disconnected(), context=b)[0]
    notice_a2 = build_connector_notices(disconnected(), context=a2)[0]

    store.dismiss(notice_a, context=a, now=now)

    assert visible_connector_notices([notice_a], store, context=a, now=now) == []
    assert visible_connector_notices([notice_b], store, context=b, now=now) == [notice_b]
    assert visible_connector_notices([notice_a2], store, context=a2, now=now) == [notice_a2]


def test_cross_scope_notice_use_fails_closed():
    store = ConnectorNoticeStore()
    a = ctx("chat-a", "project-a", "owner/repo-a")
    b = ctx("chat-b", "project-b", "owner/repo-b")
    notice_a = build_connector_notices(disconnected(), context=a)[0]

    with pytest.raises(ScopeMismatchError):
        store.dismiss(notice_a, context=b)
    with pytest.raises(ScopeMismatchError):
        store.is_dismissed(notice_a, context=b)


def test_clear_resolved_only_clears_current_scope():
    backend: dict[str, str] = {}
    store = ConnectorNoticeStore(backend=backend)
    a = ctx("chat-a", "project-a", "owner/repo-a")
    b = ctx("chat-b", "project-b", "owner/repo-b")
    notice_a = build_connector_notices(disconnected(), context=a)[0]
    notice_b = build_connector_notices(disconnected(), context=b)[0]

    store.dismiss(notice_a, context=a)
    store.dismiss(notice_b, context=b)
    store.clear_resolved([], context=a)

    assert not store.is_dismissed(notice_a, context=a)
    assert store.is_dismissed(notice_b, context=b)
