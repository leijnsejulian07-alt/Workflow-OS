from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Protocol, Sequence

from .project_scope import ScopedAccessContext, ScopedResourceRef, ScopeMismatchError


class ExternalContextProvider(Protocol):
    """Provider boundary for read-only external memory/context backends."""

    def search(self, *, namespace: str, query: str, limit: int) -> Sequence["ProviderContextHit"]: ...


@dataclass(frozen=True)
class ProviderContextHit:
    external_id: str
    text: str
    source: str
    title: str = ""


@dataclass(frozen=True)
class ScopedContextHit:
    ref: ScopedResourceRef
    text: str
    source: str
    title: str

    def require_context(self, context: ScopedAccessContext) -> None:
        self.ref.require_context(context)


class ScopedExternalContextAdapter:
    """Fail-closed read-only bridge for OpenViking-like context providers.

    Captain remains authoritative. Providers are queried only through a namespace
    derived from the exact chat/project/repository scope and Project State epoch.
    Returned hits are rebound to that same authority before use.
    """

    def __init__(self, provider: ExternalContextProvider, *, provider_name: str) -> None:
        if provider is None or not callable(getattr(provider, "search", None)):
            raise ValueError("provider with search() required")
        if not isinstance(provider_name, str) or not provider_name.strip():
            raise ValueError("provider_name required")
        self._provider = provider
        self._provider_name = provider_name.strip()

    @staticmethod
    def _require_context(context: ScopedAccessContext) -> ScopedAccessContext:
        if not isinstance(context, ScopedAccessContext):
            raise ScopeMismatchError("explicit ScopedAccessContext required for external context")
        return context

    @staticmethod
    def _namespace(context: ScopedAccessContext) -> str:
        return f"captain:{context.scope.digest}:epoch:{context.state_epoch}"

    @staticmethod
    def _clean_query(query: str) -> str:
        if not isinstance(query, str) or not query.strip() or len(query) > 4096 or "\0" in query:
            raise ValueError("invalid external context query")
        return query.strip()

    @staticmethod
    def _clean_limit(limit: int) -> int:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
            raise ValueError("invalid external context limit")
        return limit

    def search(self, *, context: ScopedAccessContext, query: str, limit: int = 8) -> tuple[ScopedContextHit, ...]:
        context = self._require_context(context)
        namespace = self._namespace(context)
        raw_hits = self._provider.search(
            namespace=namespace,
            query=self._clean_query(query),
            limit=self._clean_limit(limit),
        )
        hits: list[ScopedContextHit] = []
        for raw in raw_hits:
            if not isinstance(raw, ProviderContextHit):
                raise TypeError("provider returned invalid context hit")
            if not raw.external_id or not raw.text or not raw.source:
                raise ValueError("provider returned incomplete context hit")
            digest = hashlib.sha256(
                f"{self._provider_name}\0{raw.external_id}".encode("utf-8")
            ).hexdigest()
            ref = ScopedResourceRef.bind(
                context=context,
                resource_kind="external-context",
                resource_id=digest,
            )
            hits.append(
                ScopedContextHit(
                    ref=ref,
                    text=raw.text,
                    source=raw.source,
                    title=raw.title,
                )
            )
        return tuple(hits)
