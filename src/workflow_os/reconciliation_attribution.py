from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .reconciliation import ReconciledEvent, RevenueReconciliationLedger
from .sqlite_lifecycle import managed_connection

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class AttributedCashReceipt:
    receipt_id: str
    source_platform: str
    opportunity_id: str
    amount_eur: str
    received_at: str
    external_reference: str


def _bounded_identifier(value: object, name: str, *, max_len: int = 200) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > max_len or any(ord(ch) < 32 for ch in cleaned):
        raise ValueError(f"invalid {name}")
    return cleaned


def _evidence_digest(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("evidence_sha256 must be a lowercase SHA-256 digest")
    digest = value.strip()
    if not _SHA256_RE.fullmatch(digest):
        raise ValueError("evidence_sha256 must be a lowercase SHA-256 digest")
    return digest


def load_attributed_cash_receipt(
    legacy_db_path: str | Path,
    receipt_id: object,
) -> AttributedCashReceipt:
    """Read one already-attributed cash receipt from the legacy audit boundary.

    The opportunity ID is intentionally not supplied by the caller. It must already
    exist in cash_attributions and is re-checked against the opportunity's platform
    before the receipt may become realized-cash learning evidence.
    """

    path = Path(legacy_db_path)
    if not path.exists() or not path.is_file():
        raise ValueError("attribution ledger is unavailable")
    receipt = _bounded_identifier(receipt_id, "receipt_id")

    try:
        with managed_connection(sqlite3.connect(str(path), timeout=5.0)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only = ON")
            db.execute("PRAGMA busy_timeout = 5000")
            row = db.execute(
                """
                SELECT
                    r.receipt_id,
                    r.source_platform AS receipt_platform,
                    r.amount_eur,
                    r.received_at,
                    r.external_reference,
                    a.opportunity_id,
                    o.source_platform AS opportunity_platform
                FROM cash_receipts r
                JOIN cash_attributions a ON a.receipt_id = r.receipt_id
                JOIN opportunities o ON o.opportunity_id = a.opportunity_id
                WHERE r.receipt_id = ?
                """,
                (receipt,),
            ).fetchone()
    except sqlite3.Error as exc:
        raise ValueError("attribution ledger is unavailable or malformed") from exc

    if row is None:
        raise ValueError("cash receipt is not proven-attributed")

    platform = _bounded_identifier(row["receipt_platform"], "source_platform", max_len=80)
    opportunity_platform = _bounded_identifier(
        row["opportunity_platform"], "opportunity_source_platform", max_len=80
    )
    if platform != opportunity_platform:
        raise ValueError("receipt and opportunity source_platform must match")

    opportunity_id = _bounded_identifier(row["opportunity_id"], "opportunity_id")
    external_reference = _bounded_identifier(
        row["external_reference"], "external_reference"
    )
    received_at = _bounded_identifier(row["received_at"], "received_at")

    try:
        amount = Decimal(str(row["amount_eur"]))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("attributed cash amount is invalid") from exc
    if not amount.is_finite() or amount <= 0:
        raise ValueError("attributed cash amount is invalid")

    return AttributedCashReceipt(
        receipt_id=receipt,
        source_platform=platform,
        opportunity_id=opportunity_id,
        amount_eur=str(amount),
        received_at=received_at,
        external_reference=external_reference,
    )


def promote_attributed_cash_receipt(
    *,
    legacy_db_path: str | Path,
    reconciliation_ledger: RevenueReconciliationLedger,
    receipt_id: object,
    evidence_sha256: object,
) -> ReconciledEvent:
    """Promote only proven-attributed received cash into scaling truth.

    Source evidence remains independently required. The caller cannot override the
    opportunity or platform selected by the fail-closed attribution ledger.
    """

    if not isinstance(reconciliation_ledger, RevenueReconciliationLedger):
        raise ValueError("reconciliation_ledger must be a RevenueReconciliationLedger")
    digest = _evidence_digest(evidence_sha256)
    attributed = load_attributed_cash_receipt(legacy_db_path, receipt_id)

    return reconciliation_ledger.record_event(
        platform=attributed.source_platform,
        external_event_id=f"audit-receipt:{attributed.receipt_id}",
        opportunity_id=attributed.opportunity_id,
        event_type="CASH_RECEIVED",
        amount_eur=attributed.amount_eur,
        occurred_at=attributed.received_at,
        evidence_sha256=digest,
        currency="EUR",
    )
