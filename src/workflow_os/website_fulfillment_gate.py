"""Fail-closed pre-fulfillment gate for Website-in-a-Box.

This boundary converts an already-normalized, currently ACCEPTed Website-in-a-Box
opportunity into an immutable fixed-scope snapshot and verifies payment evidence
before bounded production may begin. It does not build, deploy, charge, or record
revenue; received cash must still be reconciled by the shared settlement ledger.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import re
from typing import Any

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_PAGES = 5


def _utc(value: str, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include timezone")
    return parsed.astimezone(timezone.utc)


def _money(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise TypeError(f"{field} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{field} must be finite and positive")
    return number


def _text(value: Any, field: str, *, max_length: int = 2048) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    text = value.strip()
    if not text or len(text) > max_length:
        raise ValueError(f"{field} is missing or malformed")
    return text


@dataclass(frozen=True)
class WebsiteScopeSnapshot:
    opportunity_id: str
    lead_id: str
    pages: int
    fixed_price_eur: float
    quote_expires_at: str
    usage_rights: str
    customer_controls_domain: bool
    recurring_maintenance: bool
    mobile_responsive: bool
    basic_seo_metadata: bool
    contact_or_cta: bool
    payment_method: str
    approval_rules: str
    source_checked_at: str
    snapshot_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class WebsitePaymentEvidence:
    opportunity_id: str
    amount_eur: float
    currency: str
    payment_reference: str
    received_at: str
    evidence_sha256: str
    payment_received: bool


@dataclass(frozen=True)
class FulfillmentGateDecision:
    state: str
    reason: str
    opportunity_id: str
    scope_sha256: str
    payment_reference: str | None = None


def _decision_value(decision: Any, field: str) -> Any:
    if isinstance(decision, dict):
        return decision.get(field)
    return getattr(decision, field, None)


def build_scope_snapshot(
    opportunity: dict[str, Any],
    decision: Any,
    *,
    now: datetime | None = None,
) -> WebsiteScopeSnapshot:
    """Freeze the exact scope of a currently queue-eligible Website-in-a-Box job."""
    if not isinstance(opportunity, dict):
        raise TypeError("opportunity must be a mapping")
    now_dt = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    opportunity_id = _text(opportunity.get("opportunity_id"), "opportunity_id", max_length=128)

    if _decision_value(decision, "opportunity_id") != opportunity_id:
        raise ValueError("opportunity decision identity mismatch")
    if _decision_value(decision, "decision") != "ACCEPT" or _decision_value(decision, "eligible_for_queue") is not True:
        raise ValueError("latest Opportunity Manager decision is not queue-eligible ACCEPT")
    if opportunity.get("category") != "website_in_a_box":
        raise ValueError("opportunity is not Website-in-a-Box")
    if opportunity.get("rights_verification_state") != "VERIFIED":
        raise ValueError("content rights are not verified")

    scope = opportunity.get("website_scope")
    if not isinstance(scope, dict):
        raise ValueError("website_scope is missing")
    pages = scope.get("pages")
    if isinstance(pages, bool) or not isinstance(pages, int) or not 1 <= pages <= _MAX_PAGES:
        raise ValueError("website page scope is invalid")
    if scope.get("recurring_maintenance") is not False:
        raise ValueError("recurring maintenance is prohibited for this vertical")
    if scope.get("customer_controls_domain") is not True:
        raise ValueError("customer-controlled domain is required")

    lead_evidence = opportunity.get("lead_evidence")
    if not isinstance(lead_evidence, dict):
        raise ValueError("lead evidence is missing")
    required_attestations = (
        lead_evidence.get("explicit_request_for_website") is True,
        lead_evidence.get("commercial_contact_consent") is True,
        lead_evidence.get("recurring_maintenance_requested") is False,
        lead_evidence.get("content_rights_attested") is True,
    )
    if not all(required_attestations):
        raise ValueError("lead consent/scope evidence is incomplete")

    expires = _utc(_text(opportunity.get("deadline"), "deadline", max_length=64), "deadline")
    checked = _utc(_text(opportunity.get("source_checked_at"), "source_checked_at", max_length=64), "source_checked_at")
    if expires <= now_dt:
        raise ValueError("quote has expired")
    if checked > now_dt:
        raise ValueError("source evidence cannot be future-dated")

    payload = {
        "opportunity_id": opportunity_id,
        "lead_id": _text(opportunity.get("campaign_id"), "campaign_id", max_length=128),
        "pages": pages,
        "fixed_price_eur": _money(opportunity.get("expected_revenue"), "expected_revenue"),
        "quote_expires_at": expires.isoformat(),
        "usage_rights": _text(opportunity.get("usage_rights"), "usage_rights"),
        "customer_controls_domain": True,
        "recurring_maintenance": False,
        "mobile_responsive": scope.get("mobile_responsive") is True,
        "basic_seo_metadata": scope.get("basic_seo_metadata") is True,
        "contact_or_cta": scope.get("contact_or_cta") is True,
        "payment_method": _text(opportunity.get("payment_method"), "payment_method", max_length=256),
        "approval_rules": _text(opportunity.get("approval_rules"), "approval_rules"),
        "source_checked_at": checked.isoformat(),
    }
    if not (payload["mobile_responsive"] and payload["basic_seo_metadata"] and payload["contact_or_cta"]):
        raise ValueError("required fixed-scope deliverables are incomplete")

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return WebsiteScopeSnapshot(**payload, snapshot_sha256=digest)


def gate_paid_fulfillment(
    snapshot: WebsiteScopeSnapshot,
    payment: WebsitePaymentEvidence,
    *,
    now: datetime | None = None,
) -> FulfillmentGateDecision:
    """Allow only paid, identity-bound, evidenced scope to proceed to bounded build.

    PASS does not prove reconciled revenue and does not perform an external side effect.
    """
    if not isinstance(snapshot, WebsiteScopeSnapshot):
        raise TypeError("snapshot must be WebsiteScopeSnapshot")
    if not isinstance(payment, WebsitePaymentEvidence):
        raise TypeError("payment must be WebsitePaymentEvidence")
    if payment.opportunity_id != snapshot.opportunity_id:
        raise ValueError("payment opportunity identity mismatch")
    if payment.payment_received is not True:
        return FulfillmentGateDecision("HOLD", "PAYMENT_NOT_CONFIRMED", snapshot.opportunity_id, snapshot.snapshot_sha256)
    if payment.currency.strip().upper() != "EUR":
        return FulfillmentGateDecision("HOLD", "PAYMENT_CURRENCY_MISMATCH", snapshot.opportunity_id, snapshot.snapshot_sha256)
    amount = _money(payment.amount_eur, "amount_eur")
    if amount + 1e-9 < snapshot.fixed_price_eur:
        return FulfillmentGateDecision("HOLD", "PAYMENT_BELOW_FIXED_PRICE", snapshot.opportunity_id, snapshot.snapshot_sha256)
    if not _SHA256_RE.fullmatch(payment.evidence_sha256):
        raise ValueError("payment evidence digest is malformed")
    reference = _text(payment.payment_reference, "payment_reference", max_length=256)
    received = _utc(payment.received_at, "received_at")
    now_dt = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if received > now_dt:
        raise ValueError("payment evidence cannot be future-dated")
    if _utc(snapshot.quote_expires_at, "quote_expires_at") <= received:
        return FulfillmentGateDecision("HOLD", "PAYMENT_AFTER_QUOTE_EXPIRY", snapshot.opportunity_id, snapshot.snapshot_sha256, reference)

    return FulfillmentGateDecision(
        "READY_FOR_BOUNDED_BUILD",
        "PAYMENT_EVIDENCE_ACCEPTED_NOT_YET_RECONCILED_AS_REVENUE",
        snapshot.opportunity_id,
        snapshot.snapshot_sha256,
        reference,
    )
