from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
import re
from typing import Any, Mapping

_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")


@dataclass(frozen=True)
class PlaidBankReceiptEvidence:
    transaction_id: str
    account_id: str
    amount_cents: int
    currency: str
    posted_date: str
    description: str
    evidence_sha256: str


def _identifier(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    cleaned = value.strip()
    if not _ID_RE.fullmatch(cleaned):
        raise ValueError(f"invalid {name}")
    return cleaned


def _credit_cents(value: object) -> int:
    """Normalize Plaid's signed amount; incoming credits are negative amounts."""
    if isinstance(value, bool):
        raise ValueError("Plaid amount must be a finite incoming credit")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Plaid amount must be a finite incoming credit") from exc
    if not amount.is_finite() or amount >= 0:
        raise ValueError("Plaid transaction is not an incoming credit")
    credit = (-amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if credit != -amount:
        raise ValueError("Plaid amount may have at most two decimal places")
    cents = int(credit * 100)
    if cents <= 0 or cents > 100_000_000_000:
        raise ValueError("Plaid credit amount is outside supported bounds")
    return cents


def normalize_plaid_bank_receipt(raw: Mapping[str, Any]) -> PlaidBankReceiptEvidence:
    """Convert one official Plaid Transactions record into immutable receipt evidence.

    This is evidence only. It never grants settlement authority by itself. Pending,
    non-EUR, outgoing, malformed, or identity-ambiguous transactions fail closed.
    """
    if not isinstance(raw, Mapping):
        raise ValueError("raw Plaid transaction must be a mapping")
    if raw.get("pending") is not False:
        raise ValueError("pending or unknown Plaid transactions cannot prove received cash")

    iso_currency_code = raw.get("iso_currency_code")
    unofficial_currency_code = raw.get("unofficial_currency_code")
    if iso_currency_code != "EUR" or unofficial_currency_code not in (None, ""):
        raise ValueError("Plaid bank receipt version 1 accepts official EUR only")

    transaction_id = _identifier(raw.get("transaction_id"), "transaction_id")
    account_id = _identifier(raw.get("account_id"), "account_id")
    amount_cents = _credit_cents(raw.get("amount"))

    posted = raw.get("date")
    if not isinstance(posted, str):
        raise ValueError("Plaid posted date must be ISO-8601 date")
    try:
        posted_date = date.fromisoformat(posted).isoformat()
    except ValueError as exc:
        raise ValueError("Plaid posted date must be ISO-8601 date") from exc

    description_raw = raw.get("name")
    if not isinstance(description_raw, str) or not description_raw.strip():
        raise ValueError("Plaid transaction description is required")
    description = description_raw.strip()
    if len(description) > 500:
        raise ValueError("Plaid transaction description exceeds supported bounds")

    material = {
        "account_id": account_id,
        "amount_cents": amount_cents,
        "currency": "EUR",
        "description": description,
        "posted_date": posted_date,
        "transaction_id": transaction_id,
    }
    evidence_sha256 = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    return PlaidBankReceiptEvidence(
        transaction_id=transaction_id,
        account_id=account_id,
        amount_cents=amount_cents,
        currency="EUR",
        posted_date=posted_date,
        description=description,
        evidence_sha256=evidence_sha256,
    )
