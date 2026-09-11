import pytest

from workflow_os.external_context import (
    ProviderContextHit,
    ScopedExternalContextAdapter,
)
from workflow_os.project_scope import (
    ProjectScope,
    ScopeMismatchError,
    ScopedAccessContext,
)


class FakeProvider:
    def __init__(self) -> None:
        self.calls = []

    def search(self, *, namespace: str, query: str, limit: int):
        self.calls.append((namespace, query, limit))
        return [
            ProviderContextHit(
                external_id="note-1",
                text="bounded context",
                source="viking://knowledge/note-1",
                title="Note 1",
            )
        ]


def ctx(project: str, epoch: int) -> ScopedAccessContext:
    return ScopedAccessContext(
        scope=ProjectScope(
            chat_id="chat-1",
            project_id=project,
            repo_scope="owner/repo",
        ),
        state_epoch=epoch,
    )


def test_external_context_is_namespaced_and_epoch_bound():
    provider = FakeProvider()
    adapter = ScopedExternalContextAdapter(provider, provider_name="openviking")
    current = ctx("alpha", 3)

    hit = adapter.search(context=current, query="architecture", limit=4)[0]

    namespace, query, limit = provider.calls[-1]
    assert namespace == f"captain:{current.scope.digest}:epoch:3"
    assert "alpha" not in namespace
    assert query == "architecture"
    assert limit == 4
    hit.require_context(current)

    with pytest.raises(ScopeMismatchError):
        hit.require_context(ctx("beta", 3))
    with pytest.raises(ScopeMismatchError):
        hit.require_context(ctx("alpha", 4))


def test_epoch_change_uses_new_provider_namespace():
    provider = FakeProvider()
    adapter = ScopedExternalContextAdapter(provider, provider_name="openviking")

    adapter.search(context=ctx("alpha", 7), query="one")
    adapter.search(context=ctx("alpha", 8), query="two")

    assert provider.calls[0][0] != provider.calls[1][0]


def test_unscoped_or_malformed_requests_fail_closed():
    provider = FakeProvider()
    adapter = ScopedExternalContextAdapter(provider, provider_name="openviking")

    with pytest.raises(ScopeMismatchError):
        adapter.search(context=None, query="x")
    with pytest.raises(ValueError):
        adapter.search(context=ctx("alpha", 1), query="")
    with pytest.raises(ValueError):
        adapter.search(context=ctx("alpha", 1), query="x", limit=0)
