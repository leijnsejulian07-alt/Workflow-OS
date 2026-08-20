from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_EVENT_JSON_BYTES = 64 * 1024


def _canonical(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if len(encoded.encode("utf-8")) > MAX_EVENT_JSON_BYTES:
        raise ValueError("event payload exceeds 64 KiB")
    return encoded


def _utc(value: str | None = None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True)
class CashReceipt:
    receipt_id: str
    source_platform: str
    amount_eur: float
    received_at: str
    external_reference: str


class AuditRevenueLedger:
    """Append-only audit + reconciled cash boundary.

    Estimated opportunity revenue never enters cash_receipts. A receipt requires a
    stable external reference and is idempotent on receipt_id. Audit rows form a
    simple hash chain so accidental mutation is detectable during verification.

    Opportunity attribution is stored separately from the immutable cash receipt so
    existing receipts remain backwards-compatible while new autonomous learning can
    require a proven opportunity link before treating cash as campaign evidence.
    """

    def __init__(self, path: str | Path):
        self.path = str(path)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    occurred_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    subject_id TEXT,
                    event_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL UNIQUE
                );
                CREATE TABLE IF NOT EXISTS cash_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    source_platform TEXT NOT NULL,
                    amount_eur REAL NOT NULL CHECK(amount_eur > 0),
                    received_at TEXT NOT NULL,
                    external_reference TEXT NOT NULL,
                    receipt_json TEXT NOT NULL,
                    UNIQUE(source_platform, external_reference)
                );
                CREATE TABLE IF NOT EXISTS cash_attributions (
                    receipt_id TEXT PRIMARY KEY,
                    opportunity_id TEXT NOT NULL,
                    attributed_at TEXT NOT NULL,
                    FOREIGN KEY(receipt_id) REFERENCES cash_receipts(receipt_id),
                    FOREIGN KEY(opportunity_id) REFERENCES opportunities(opportunity_id)
                );
                CREATE INDEX IF NOT EXISTS idx_cash_attributions_opportunity
                    ON cash_attributions(opportunity_id);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA busy_timeout = 5000")
        return db

    def append_event(self, event_id: str, event_type: str, payload: dict[str, Any], *, subject_id: str | None = None, occurred_at: str | None = None) -> str:
        if not event_id.strip() or not event_type.strip():
            raise ValueError("event_id and event_type are required")
        occurred = _utc(occurred_at)
        event_json = _canonical(payload)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT event_hash, event_type, subject_id, occurred_at, event_json FROM audit_events WHERE event_id=?", (event_id,)).fetchone()
            if existing:
                if (existing["event_type"], existing["subject_id"], existing["occurred_at"], existing["event_json"]) != (event_type, subject_id, occurred, event_json):
                    raise ValueError("event_id already exists with different content")
                return str(existing["event_hash"])
            row = db.execute("SELECT event_hash FROM audit_events ORDER BY id DESC LIMIT 1").fetchone()
            previous = str(row["event_hash"]) if row else "GENESIS"
            material = "\n".join((previous, event_id, occurred, event_type, subject_id or "", event_json))
            digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
            db.execute("INSERT INTO audit_events(event_id, occurred_at, event_type, subject_id, event_json, previous_hash, event_hash) VALUES(?,?,?,?,?,?,?)", (event_id, occurred, event_type, subject_id, event_json, previous, digest))
            return digest

    def record_cash(self, receipt: CashReceipt) -> None:
        if not receipt.receipt_id.strip() or not receipt.source_platform.strip() or not receipt.external_reference.strip():
            raise ValueError("receipt identity fields are required")
        amount = float(receipt.amount_eur)
        if not 0 < amount < 1_000_000:
            raise ValueError("cash amount outside allowed bounds")
        received = _utc(receipt.received_at)
        payload = _canonical({"receipt_id": receipt.receipt_id, "source_platform": receipt.source_platform, "amount_eur": amount, "received_at": received, "external_reference": receipt.external_reference})
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT receipt_json FROM cash_receipts WHERE receipt_id=?", (receipt.receipt_id,)).fetchone()
            if existing:
                if existing["receipt_json"] != payload:
                    raise ValueError("receipt_id already exists with different content")
                return
            db.execute("INSERT INTO cash_receipts(receipt_id, source_platform, amount_eur, received_at, external_reference, receipt_json) VALUES(?,?,?,?,?,?)", (receipt.receipt_id, receipt.source_platform, amount, received, receipt.external_reference, payload))

    def attribute_cash(self, receipt_id: str, opportunity_id: str, *, attributed_at: str | None = None) -> None:
        """Link an already-reconciled receipt to one known opportunity, fail-closed.

        Attribution is only accepted when both records exist and their source_platform
        values match exactly. Reusing a receipt for another opportunity is rejected.
        This prevents settlement cash from becoming autonomous scaling evidence for
        the wrong campaign merely because IDs were guessed or adapters drifted.
        """

        receipt_id = receipt_id.strip()
        opportunity_id = opportunity_id.strip()
        if not receipt_id or not opportunity_id:
            raise ValueError("receipt_id and opportunity_id are required")
        attributed = _utc(attributed_at)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            receipt = db.execute(
                "SELECT source_platform FROM cash_receipts WHERE receipt_id=?",
                (receipt_id,),
            ).fetchone()
            if receipt is None:
                raise ValueError("cash receipt does not exist")
            opportunity = db.execute(
                "SELECT source_platform FROM opportunities WHERE opportunity_id=?",
                (opportunity_id,),
            ).fetchone()
            if opportunity is None:
                raise ValueError("opportunity does not exist")
            if str(receipt["source_platform"]) != str(opportunity["source_platform"]):
                raise ValueError("receipt and opportunity source_platform must match")
            existing = db.execute(
                "SELECT opportunity_id FROM cash_attributions WHERE receipt_id=?",
                (receipt_id,),
            ).fetchone()
            if existing:
                if existing["opportunity_id"] != opportunity_id:
                    raise ValueError("receipt is already attributed to another opportunity")
                return
            db.execute(
                "INSERT INTO cash_attributions(receipt_id, opportunity_id, attributed_at) VALUES(?,?,?)",
                (receipt_id, opportunity_id, attributed),
            )

        self.append_event(
            "cash-attribution:" + hashlib.sha256(receipt_id.encode("utf-8")).hexdigest(),
            "cash.attributed",
            {"receipt_id": receipt_id, "opportunity_id": opportunity_id},
            subject_id=opportunity_id,
            occurred_at=attributed,
        )

    def realized_cash_eur(self, opportunity_id: str) -> float:
        opportunity_id = opportunity_id.strip()
        if not opportunity_id:
            raise ValueError("opportunity_id is required")
        with self._connect() as db:
            row = db.execute(
                """
                SELECT COALESCE(SUM(r.amount_eur), 0) AS total
                FROM cash_attributions a
                JOIN cash_receipts r ON r.receipt_id = a.receipt_id
                WHERE a.opportunity_id=?
                """,
                (opportunity_id,),
            ).fetchone()
        return float(row["total"])

    def gross_cash_eur(self) -> float:
        with self._connect() as db:
            row = db.execute("SELECT COALESCE(SUM(amount_eur), 0) AS total FROM cash_receipts").fetchone()
        return float(row["total"])

    def verify_audit_chain(self) -> bool:
        previous = "GENESIS"
        with self._connect() as db:
            rows = db.execute("SELECT event_id, occurred_at, event_type, subject_id, event_json, previous_hash, event_hash FROM audit_events ORDER BY id ASC").fetchall()
        for row in rows:
            if row["previous_hash"] != previous:
                return False
            material = "\n".join((previous, row["event_id"], row["occurred_at"], row["event_type"], row["subject_id"] or "", row["event_json"]))
            digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
            if digest != row["event_hash"]:
                return False
            previous = digest
        return True
