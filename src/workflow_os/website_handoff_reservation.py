"""Idempotent handoff reservation for QA-passed Website-in-a-Box artifacts.

This boundary binds a QA-passed static artifact to one customer-controlled handoff
intent in the shared SideEffectLedger. It does not deploy, upload, modify DNS,
charge money, or begin an external execution attempt.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .side_effects import SideEffectLedger, SideEffectRecord
from .website_fulfillment_gate import WebsiteScopeSnapshot
from .website_static_build import WebsiteBuildArtifact, WebsiteQADecision

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_HANDOFF_MODES = {"CUSTOMER_DOWNLOAD", "CUSTOMER_CONTROLLED_HOSTING_API"}


@dataclass(frozen=True)
class WebsiteHandoffIntent:
    opportunity_id: str
    scope_sha256: str
    manifest_sha256: str
    handoff_mode: str
    customer_controls_domain: bool
    customer_controls_hosting: bool
    target_reference: str


@dataclass(frozen=True)
class WebsiteHandoffReservation:
    state: str
    reason: str
    idempotency_key: str
    side_effect: SideEffectRecord | None


def _text(value: Any, field: str, *, max_length: int = 500) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    text = value.strip()
    if not text or len(text) > max_length:
        raise ValueError(f"{field} is missing or malformed")
    return text


def reserve_website_handoff(
    snapshot: WebsiteScopeSnapshot,
    artifact: WebsiteBuildArtifact,
    qa: WebsiteQADecision,
    intent: WebsiteHandoffIntent,
    ledger: SideEffectLedger,
) -> WebsiteHandoffReservation:
    """Reserve exactly one bounded handoff intent after successful static QA."""
    if not isinstance(snapshot, WebsiteScopeSnapshot):
        raise TypeError("snapshot must be WebsiteScopeSnapshot")
    if not isinstance(artifact, WebsiteBuildArtifact):
        raise TypeError("artifact must be WebsiteBuildArtifact")
    if not isinstance(qa, WebsiteQADecision):
        raise TypeError("qa must be WebsiteQADecision")
    if not isinstance(intent, WebsiteHandoffIntent):
        raise TypeError("intent must be WebsiteHandoffIntent")
    if not isinstance(ledger, SideEffectLedger):
        raise TypeError("ledger must be SideEffectLedger")

    if qa.state != "PASS_FOR_HANDOFF_RESERVATION":
        return WebsiteHandoffReservation("HOLD", "STATIC_QA_NOT_PASSED", "", None)
    if qa.opportunity_id != snapshot.opportunity_id or qa.manifest_sha256 != artifact.manifest_sha256:
        raise ValueError("QA identity mismatch")
    if artifact.opportunity_id != snapshot.opportunity_id or artifact.scope_sha256 != snapshot.snapshot_sha256:
        raise ValueError("artifact identity mismatch")
    if intent.opportunity_id != snapshot.opportunity_id:
        raise ValueError("handoff opportunity identity mismatch")
    if intent.scope_sha256 != snapshot.snapshot_sha256 or intent.manifest_sha256 != artifact.manifest_sha256:
        raise ValueError("handoff scope/artifact identity mismatch")
    if not _SHA256_RE.fullmatch(intent.scope_sha256) or not _SHA256_RE.fullmatch(intent.manifest_sha256):
        raise ValueError("handoff digest is malformed")
    if snapshot.customer_controls_domain is not True or intent.customer_controls_domain is not True:
        return WebsiteHandoffReservation("HOLD", "CUSTOMER_CONTROLLED_DOMAIN_REQUIRED", "", None)
    if intent.customer_controls_hosting is not True:
        return WebsiteHandoffReservation("HOLD", "CUSTOMER_CONTROLLED_HOSTING_REQUIRED", "", None)

    mode = _text(intent.handoff_mode, "handoff_mode", max_length=64).upper()
    if mode not in _ALLOWED_HANDOFF_MODES:
        return WebsiteHandoffReservation("HOLD", "UNSUPPORTED_HANDOFF_MODE", "", None)
    target_reference = _text(intent.target_reference, "target_reference")

    # A stable key permanently binds this scope + built artifact to one handoff mode.
    key = f"website-handoff:{snapshot.opportunity_id}:{artifact.manifest_sha256}:{mode}"[:200]
    payload = {
        "opportunity_id": snapshot.opportunity_id,
        "scope_sha256": snapshot.snapshot_sha256,
        "manifest_sha256": artifact.manifest_sha256,
        "handoff_mode": mode,
        "customer_controls_domain": True,
        "customer_controls_hosting": True,
        "target_reference": target_reference,
        "file_count": len(artifact.files),
        "total_bytes": artifact.total_bytes,
    }
    record = ledger.reserve(
        idempotency_key=key,
        action="WEBSITE_HANDOFF",
        target=target_reference,
        payload=payload,
        max_attempts=3,
    )
    if record.state != "RESERVED":
        return WebsiteHandoffReservation("HOLD", f"HANDOFF_ALREADY_{record.state}", key, record)
    return WebsiteHandoffReservation(
        "RESERVED_ONLY_NO_EXTERNAL_ACTION",
        "QA_PASSED_HANDOFF_INTENT_BOUND_TO_SIDE_EFFECT_LEDGER",
        key,
        record,
    )
