from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from urllib.parse import urlsplit, urlunsplit

from .project_scope import ScopedAccessContext, ScopedResourceRef


_EVIDENCE_RELATIONSHIPS = frozenset({"supports", "challenges", "context"})


def _safe_source_url(url: str) -> str:
    if not isinstance(url, str):
        raise ValueError("source_url must be a string")
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("source_url must be absolute http(s)")
    # Never persist query strings/fragments: they may contain auth tokens or user identifiers.
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", "", ""))


def _clean_text(value: str, field: str, *, max_len: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    value = " ".join(value.split())
    if not value or len(value) > max_len:
        raise ValueError(f"invalid {field}")
    return value


def _clean_relationship(value: str) -> str:
    value = _clean_text(value, "relationship", max_len=32).lower()
    if value not in _EVIDENCE_RELATIONSHIPS:
        raise ValueError("relationship must be supports, challenges, or context")
    return value


@dataclass(frozen=True)
class ResearchEvidence:
    ref: ScopedResourceRef
    claim_id: str
    source_url: str
    source_title: str
    excerpt_digest: str
    relationship: str = "supports"

    def require_context(self, context: ScopedAccessContext) -> None:
        self.ref.require_context(context)


@dataclass(frozen=True)
class ClaimCoverage:
    """Secret-free quality signal for one claim in one exact Captain authority context."""

    claim_id: str
    evidence_count: int
    supporting_count: int
    challenging_count: int
    context_count: int
    distinct_source_hosts: int

    @property
    def has_challenge(self) -> bool:
        return self.challenging_count > 0


class ResearchEvidenceLedger:
    """Secret-minimizing provenance ledger bound to Captain's current authority epoch."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, int, str], ResearchEvidence] = {}

    @staticmethod
    def _key(ref: ScopedResourceRef) -> tuple[str, int, str]:
        return (ref.scope_digest, ref.state_epoch, ref.resource_id)

    def record(
        self,
        *,
        context: ScopedAccessContext,
        evidence_id: str,
        claim_id: str,
        source_url: str,
        source_title: str,
        excerpt: str,
        relationship: str = "supports",
    ) -> ResearchEvidence:
        if not isinstance(context, ScopedAccessContext):
            raise ValueError("explicit ScopedAccessContext required")
        evidence_id = _clean_text(evidence_id, "evidence_id", max_len=128)
        claim_id = _clean_text(claim_id, "claim_id", max_len=128)
        source_title = _clean_text(source_title, "source_title", max_len=512)
        excerpt = _clean_text(excerpt, "excerpt", max_len=20_000)
        relationship = _clean_relationship(relationship)
        ref = ScopedResourceRef.bind(
            context=context,
            resource_kind="research-evidence",
            resource_id=evidence_id,
        )
        item = ResearchEvidence(
            ref=ref,
            claim_id=claim_id,
            source_url=_safe_source_url(source_url),
            source_title=source_title,
            excerpt_digest=sha256(excerpt.encode("utf-8")).hexdigest(),
            relationship=relationship,
        )
        self._items[self._key(ref)] = item
        return item

    def get(
        self,
        *,
        context: ScopedAccessContext,
        evidence_id: str,
    ) -> ResearchEvidence | None:
        if not isinstance(context, ScopedAccessContext):
            raise ValueError("explicit ScopedAccessContext required")
        evidence_id = _clean_text(evidence_id, "evidence_id", max_len=128)
        probe = ScopedResourceRef.bind(
            context=context,
            resource_kind="research-evidence",
            resource_id=evidence_id,
        )
        item = self._items.get(self._key(probe))
        if item is None:
            return None
        item.require_context(context)
        return item

    def list_for_context(self, *, context: ScopedAccessContext) -> tuple[ResearchEvidence, ...]:
        if not isinstance(context, ScopedAccessContext):
            raise ValueError("explicit ScopedAccessContext required")
        found: list[ResearchEvidence] = []
        for (scope_digest, epoch, _), item in self._items.items():
            if scope_digest == context.scope.digest and epoch == context.state_epoch:
                item.require_context(context)
                found.append(item)
        return tuple(sorted(found, key=lambda item: item.ref.resource_id))

    def list_for_claim(
        self,
        *,
        context: ScopedAccessContext,
        claim_id: str,
    ) -> tuple[ResearchEvidence, ...]:
        claim_id = _clean_text(claim_id, "claim_id", max_len=128)
        return tuple(
            item
            for item in self.list_for_context(context=context)
            if item.claim_id == claim_id
        )

    def coverage_for_claim(
        self,
        *,
        context: ScopedAccessContext,
        claim_id: str,
    ) -> ClaimCoverage:
        claim_id = _clean_text(claim_id, "claim_id", max_len=128)
        evidence = self.list_for_claim(context=context, claim_id=claim_id)
        hosts = {urlsplit(item.source_url).hostname for item in evidence}
        return ClaimCoverage(
            claim_id=claim_id,
            evidence_count=len(evidence),
            supporting_count=sum(item.relationship == "supports" for item in evidence),
            challenging_count=sum(item.relationship == "challenges" for item in evidence),
            context_count=sum(item.relationship == "context" for item in evidence),
            distinct_source_hosts=len(hosts),
        )