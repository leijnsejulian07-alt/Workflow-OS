from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from .adapters.awin_transaction_http_transport import AwinTransactionFetchResult
from .audit import AuditRevenueLedger
from .awin_transaction_evidence import (
    AwinTransactionEvidence,
    record_awin_transaction_evidence,
)
from .ledger import OpportunityLedger


_ALLOWED_STATUSES = {"pending", "approved", "declined", "deleted"}
_CLICK_REF_PREFIX = "workflow-os:"


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Awin {name} must be an object")
    return value


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"Awin {name} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Awin {name} must be a positive integer") from exc
    if parsed <= 0 or str(parsed) != str(value).strip():
        raise ValueError(f"Awin {name} must be a positive integer")
    return parsed


def _utc_api_timestamp(value: object, name: str, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Awin {name} must be an ISO-8601 timestamp")
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Awin {name} must be an ISO-8601 timestamp") from exc

    # The transport pins the Awin transaction query to timezone=UTC. Historical
    # Awin responses may omit an explicit offset, so offset-less API timestamps
    # are interpreted only inside this UTC-pinned transport boundary.
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _opportunity_from_click_ref(value: object) -> tuple[str, str]:
    click_refs = _mapping(value, "clickRefs")
    click_ref = click_refs.get("clickRef")
    if not isinstance(click_ref, str):
        raise ValueError("Awin clickRefs.clickRef must be a string")
    click_ref = click_ref.strip()
    if not click_ref.startswith(_CLICK_REF_PREFIX):
        raise ValueError("Awin clickRef is not a Workflow OS attribution reference")
    opportunity_id = click_ref[len(_CLICK_REF_PREFIX) :]
    if not opportunity_id or opportunity_id != opportunity_id.strip():
        raise ValueError("Awin clickRef contains an invalid Workflow OS opportunity id")
    return opportunity_id, click_ref


def canonicalize_awin_api_transaction(
    fetch_result: AwinTransactionFetchResult,
    transaction: Mapping[str, Any],
) -> tuple[str, Mapping[str, Any]]:
    """Map one official Awin API row into the existing canonical evidence shape.

    The response-body SHA-256 from the bounded HTTP transport is carried forward
    unchanged so the canonical evidence remains bound to the exact retrieved body.
    No Awin commission/status is treated as received cash here.
    """

    if not isinstance(fetch_result, AwinTransactionFetchResult):
        raise TypeError("fetch_result must be an AwinTransactionFetchResult")
    row = _mapping(transaction, "transaction")

    publisher_id = _positive_int(row.get("publisherId"), "publisherId")
    if publisher_id != fetch_result.publisher_id:
        raise ValueError("Awin transaction publisherId does not match the requested publisher")

    advertiser_id = _positive_int(row.get("advertiserId"), "advertiserId")
    if (
        fetch_result.advertiser_id is not None
        and advertiser_id != fetch_result.advertiser_id
    ):
        raise ValueError("Awin transaction advertiserId does not match the requested advertiser")

    transaction_id = _positive_int(row.get("id"), "transaction id")
    status = row.get("commissionStatus")
    if not isinstance(status, str) or status not in _ALLOWED_STATUSES:
        raise ValueError("unsupported Awin commissionStatus")

    commission = _mapping(row.get("commissionAmount"), "commissionAmount")
    currency = commission.get("currency")
    if currency != "EUR":
        raise ValueError("Awin transaction ingestion version 1 accepts EUR only")
    if "amount" not in commission:
        raise ValueError("Awin commissionAmount.amount is required")

    opportunity_id, click_ref = _opportunity_from_click_ref(row.get("clickRefs"))
    transaction_at = _utc_api_timestamp(row.get("transactionDate"), "transactionDate")
    validation_at = _utc_api_timestamp(
        row.get("validationDate"), "validationDate", optional=True
    )
    if status in {"approved", "declined", "deleted"} and validation_at is None:
        raise ValueError("validated Awin commissionStatus requires validationDate")

    canonical = {
        "transaction_id": str(transaction_id),
        "publisher_id": publisher_id,
        "advertiser_id": advertiser_id,
        "status": status,
        "commission_eur": commission.get("amount"),
        "currency": "EUR",
        "transaction_at": transaction_at,
        "validation_at": validation_at,
        "click_ref": click_ref,
        "evidence_sha256": fetch_result.evidence_sha256,
    }
    return opportunity_id, canonical


def ingest_awin_transaction_fetch(
    fetch_result: AwinTransactionFetchResult,
    *,
    opportunity_ledger: OpportunityLedger,
    audit_ledger: AuditRevenueLedger,
) -> tuple[AwinTransactionEvidence, ...]:
    """Canonicalize and record every transaction from one bounded Awin response.

    Each row is attributed exclusively from the Workflow OS-owned clickRef. Unknown
    opportunities, identity drift, malformed rows, non-EUR values, or invalid status
    transitions fail closed. The downstream evidence recorder remains idempotent.
    """

    recorded: list[AwinTransactionEvidence] = []
    seen: set[tuple[int, str]] = set()
    for transaction in fetch_result.transactions:
        opportunity_id, canonical = canonicalize_awin_api_transaction(
            fetch_result, transaction
        )
        row_key = (int(canonical["transaction_id"]), str(canonical["status"]))
        if row_key in seen:
            raise ValueError("duplicate Awin transaction/status row in one API response")
        seen.add(row_key)
        recorded.append(
            record_awin_transaction_evidence(
                canonical,
                expected_opportunity_id=opportunity_id,
                opportunity_ledger=opportunity_ledger,
                audit_ledger=audit_ledger,
            )
        )
    return tuple(recorded)
