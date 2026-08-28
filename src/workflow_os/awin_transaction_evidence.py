from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping

from .audit import AuditRevenueLedger
from .ledger import OpportunityLedger

_ALLOWED_STATUSES = {"pending", "approved", "declined", "deleted"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")


@dataclass(frozen=True)
class AwinTransactionEvidence:
    transaction_id: str
    opportunity_id: str
    publisher_id: int
    advertiser_id: int
    status: str
    commission_cents: int
    currency: str
    transaction_at: str
    validation_at: str | None
    click_ref: str
    evidence_sha256: str

    @property
    def proves_received_cash(self) -> bool:
        return False


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    cleaned = value.strip()
    if not _ID_RE.fullmatch(cleaned):
        raise ValueError(f"invalid {name}")
    return cleaned


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if parsed <= 0 or str(parsed) != str(value).strip():
        raise ValueError(f"{name} must be a positive integer")
    return parsed


def _timestamp(value: object, name: str, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a timezone-aware ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be a timezone-aware ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware ISO-8601 timestamp")
    return parsed.isoformat()


def _commission_to_cents(value: object) -> int:
    if isinstance(value, bool) or (isinstance(value, float) and not math.isfinite(value)):
        raise ValueError("commission_eur must be finite and non-negative")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("commission_eur must be finite and non-negative") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError("commission_eur must be finite and non-negative")
    quantized = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if quantized != amount:
        raise ValueError("commission_eur may have at most two decimal places")
    cents = int(quantized * 100)
    if cents > 100_000_000_000:
        raise ValueError("commission_eur is outside supported bounds")
    return cents


def _digest(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("evidence_sha256 must be a lowercase SHA-256 digest")
    cleaned = value.strip()
    if not _SHA256_RE.fullmatch(cleaned):
        raise ValueError("evidence_sha256 must be a lowercase SHA-256 digest")
    return cleaned


def normalize_awin_transaction(
    raw: Mapping[str, Any], *, expected_opportunity_id: str
) -> AwinTransactionEvidence:
    if not isinstance(raw, Mapping):
        raise ValueError("raw Awin transaction must be a mapping")

    opportunity_id = _identifier(expected_opportunity_id, "expected_opportunity_id")
    transaction_id = _identifier(raw.get("transaction_id"), "transaction_id")
    publisher_id = _positive_int(raw.get("publisher_id"), "publisher_id")
    advertiser_id = _positive_int(raw.get("advertiser_id"), "advertiser_id")

    status = raw.get("status")
    if not isinstance(status, str) or status not in _ALLOWED_STATUSES:
        raise ValueError("unsupported Awin transaction status")

    currency = raw.get("currency")
    if currency != "EUR":
        raise ValueError("Awin transaction evidence version 1 accepts EUR only")

    click_ref = _identifier(raw.get("click_ref"), "click_ref")
    expected_click_ref = f"workflow-os:{opportunity_id}"
    if click_ref != expected_click_ref:
        raise ValueError("Awin click_ref does not match the expected Workflow OS opportunity")

    transaction_at = _timestamp(raw.get("transaction_at"), "transaction_at")
    validation_at = _timestamp(raw.get("validation_at"), "validation_at", optional=True)
    if status in {"approved", "declined", "deleted"} and validation_at is None:
        raise ValueError("validated Awin status requires validation_at evidence")

    return AwinTransactionEvidence(
        transaction_id=transaction_id,
        opportunity_id=opportunity_id,
        publisher_id=publisher_id,
        advertiser_id=advertiser_id,
        status=status,
        commission_cents=_commission_to_cents(raw.get("commission_eur")),
        currency="EUR",
        transaction_at=str(transaction_at),
        validation_at=validation_at,
        click_ref=click_ref,
        evidence_sha256=_digest(raw.get("evidence_sha256")),
    )


def record_awin_transaction_evidence(
    raw: Mapping[str, Any],
    *,
    expected_opportunity_id: str,
    opportunity_ledger: OpportunityLedger,
    audit_ledger: AuditRevenueLedger,
) -> AwinTransactionEvidence:
    evidence = normalize_awin_transaction(
        raw, expected_opportunity_id=expected_opportunity_id
    )
    if opportunity_ledger.latest_decision(evidence.opportunity_id) is None:
        raise ValueError("Awin transaction references an unknown Workflow OS opportunity")

    payload = {
        "platform": "awin",
        "transaction_id": evidence.transaction_id,
        "opportunity_id": evidence.opportunity_id,
        "publisher_id": evidence.publisher_id,
        "advertiser_id": evidence.advertiser_id,
        "status": evidence.status,
        "commission_eur": evidence.commission_cents / 100,
        "currency": evidence.currency,
        "transaction_at": evidence.transaction_at,
        "validation_at": evidence.validation_at,
        "click_ref": evidence.click_ref,
        "evidence_sha256": evidence.evidence_sha256,
        "proves_received_cash": False,
    }
    event_material = f"awin:{evidence.publisher_id}:{evidence.transaction_id}"
    event_id = "awin-transaction:" + hashlib.sha256(event_material.encode("utf-8")).hexdigest()
    occurred_at = evidence.validation_at or evidence.transaction_at
    audit_ledger.append_event(
        event_id,
        "affiliate.awin.transaction_evidence",
        payload,
        subject_id=evidence.opportunity_id,
        occurred_at=occurred_at,
    )
    return evidence
