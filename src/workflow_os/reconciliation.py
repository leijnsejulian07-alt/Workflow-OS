from __future__ import annotations

import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from .performance import RealizedCashDecision, decide_from_realized_cash
from .sqlite_lifecycle import managed_connection

SCHEMA_VERSION = 1
_ALLOWED_EVENT_TYPES = {
    "CASH_RECEIVED",
    "CASH_REVERSED",
    "COST_INCURRED",
    "COST_REVERSED",
}
_REVERSAL_TARGET = {
    "CASH_REVERSED": "CASH_RECEIVED",
    "COST_REVERSED": "COST_INCURRED",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ReconciledEvent:
    platform: str
    external_event_id: str
    opportunity_id: str
    event_type: str
    amount_cents: int
    occurred_at: str
    evidence_sha256: str
    reference_external_event_id: str | None = None


@dataclass(frozen=True)
class RealizedSummary:
    opportunity_id: str
    realized_cash_eur: float
    reconciled_cost_eur: float
    realized_profit_eur: float
    sample_count: int


class RevenueReconciliationLedger:
    """Local-first ledger for evidence-backed realized cash and reconciled costs.

    Version 1 intentionally accepts EUR only. Multi-currency conversion must not be
    guessed: a future FX adapter must provide independently verifiable conversion
    evidence before non-EUR events may enter scaling truth.
    """

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout = 5000")
        return db

    def _init_schema(self) -> None:
        with managed_connection(self._connect()) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS reconciliation_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reconciliation_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    external_event_id TEXT NOT NULL,
                    opportunity_id TEXT NOT NULL,
                    event_type TEXT NOT NULL CHECK(event_type IN (
                        'CASH_RECEIVED','CASH_REVERSED','COST_INCURRED','COST_REVERSED'
                    )),
                    currency TEXT NOT NULL CHECK(currency = 'EUR'),
                    amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
                    occurred_at TEXT NOT NULL,
                    evidence_sha256 TEXT NOT NULL,
                    reference_external_event_id TEXT,
                    UNIQUE(platform, external_event_id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_one_reversal_per_event
                    ON reconciliation_events(platform, reference_external_event_id)
                    WHERE reference_external_event_id IS NOT NULL;
                CREATE INDEX IF NOT EXISTS idx_reconciliation_opportunity
                    ON reconciliation_events(opportunity_id, id);
                """
            )
            db.execute(
                "INSERT INTO reconciliation_meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),),
            )

    @staticmethod
    def _identifier(value: object, name: str, *, max_len: int = 200) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{name} must be a string")
        cleaned = value.strip()
        if not cleaned or len(cleaned) > max_len or any(ord(ch) < 32 for ch in cleaned):
            raise ValueError(f"invalid {name}")
        return cleaned

    @staticmethod
    def _timestamp(value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("occurred_at must be an ISO-8601 timestamp")
        text = value.strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("occurred_at must be an ISO-8601 timestamp") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone offset")
        return parsed.isoformat()

    @staticmethod
    def _amount_to_cents(value: object) -> int:
        if isinstance(value, bool):
            raise ValueError("amount_eur must be a positive finite amount")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("amount_eur must be a positive finite amount")
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError("amount_eur must be a positive finite amount") from exc
        if not amount.is_finite() or amount <= 0:
            raise ValueError("amount_eur must be a positive finite amount")
        quantized = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if quantized != amount:
            raise ValueError("amount_eur may have at most two decimal places")
        cents = int(quantized * 100)
        if cents <= 0 or cents > 100_000_000_000:
            raise ValueError("amount_eur is outside supported bounds")
        return cents

    @staticmethod
    def _evidence_digest(value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("evidence_sha256 must be a lowercase SHA-256 digest")
        digest = value.strip()
        if not _SHA256_RE.fullmatch(digest):
            raise ValueError("evidence_sha256 must be a lowercase SHA-256 digest")
        return digest

    def record_event(
        self,
        *,
        platform: object,
        external_event_id: object,
        opportunity_id: object,
        event_type: object,
        amount_eur: object,
        occurred_at: object,
        evidence_sha256: object,
        currency: object = "EUR",
        reference_external_event_id: object | None = None,
    ) -> ReconciledEvent:
        platform_value = self._identifier(platform, "platform", max_len=80)
        event_id = self._identifier(external_event_id, "external_event_id")
        opportunity = self._identifier(opportunity_id, "opportunity_id")
        if not isinstance(event_type, str) or event_type not in _ALLOWED_EVENT_TYPES:
            raise ValueError("unsupported reconciliation event_type")
        if currency != "EUR":
            raise ValueError("version 1 accepts EUR only; unverifiable FX must fail closed")
        amount_cents = self._amount_to_cents(amount_eur)
        timestamp = self._timestamp(occurred_at)
        digest = self._evidence_digest(evidence_sha256)

        reference: str | None = None
        if event_type in _REVERSAL_TARGET:
            reference = self._identifier(
                reference_external_event_id, "reference_external_event_id"
            )
        elif reference_external_event_id is not None:
            raise ValueError("non-reversal events may not reference another event")

        event = ReconciledEvent(
            platform=platform_value,
            external_event_id=event_id,
            opportunity_id=opportunity,
            event_type=event_type,
            amount_cents=amount_cents,
            occurred_at=timestamp,
            evidence_sha256=digest,
            reference_external_event_id=reference,
        )

        with managed_connection(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM reconciliation_events WHERE platform=? AND external_event_id=?",
                (platform_value, event_id),
            ).fetchone()
            if existing:
                if self._row_matches(existing, event):
                    return event
                raise ValueError("external event ID already exists with different evidence")

            if reference is not None:
                original = db.execute(
                    "SELECT * FROM reconciliation_events WHERE platform=? AND external_event_id=?",
                    (platform_value, reference),
                ).fetchone()
                if original is None:
                    raise ValueError("reversal target does not exist")
                if original["event_type"] != _REVERSAL_TARGET[event_type]:
                    raise ValueError("reversal target has incompatible event type")
                if original["opportunity_id"] != opportunity:
                    raise ValueError("reversal target belongs to a different opportunity")
                if int(original["amount_cents"]) != amount_cents:
                    raise ValueError("only full evidence-backed reversals are supported")

            try:
                db.execute(
                    """
                    INSERT INTO reconciliation_events(
                        platform, external_event_id, opportunity_id, event_type, currency,
                        amount_cents, occurred_at, evidence_sha256, reference_external_event_id
                    ) VALUES(?, ?, ?, ?, 'EUR', ?, ?, ?, ?)
                    """,
                    (
                        platform_value,
                        event_id,
                        opportunity,
                        event_type,
                        amount_cents,
                        timestamp,
                        digest,
                        reference,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("event conflicts with an existing reconciliation record") from exc
        return event

    @staticmethod
    def _row_matches(row: sqlite3.Row, event: ReconciledEvent) -> bool:
        return (
            row["opportunity_id"] == event.opportunity_id
            and row["event_type"] == event.event_type
            and int(row["amount_cents"]) == event.amount_cents
            and row["occurred_at"] == event.occurred_at
            and row["evidence_sha256"] == event.evidence_sha256
            and row["reference_external_event_id"] == event.reference_external_event_id
            and row["currency"] == "EUR"
        )

    def realized_summary(self, opportunity_id: object) -> RealizedSummary:
        opportunity = self._identifier(opportunity_id, "opportunity_id")
        with managed_connection(self._connect()) as db:
            row = db.execute(
                """
                SELECT
                    COALESCE(SUM(CASE
                        WHEN event_type='CASH_RECEIVED' THEN amount_cents
                        WHEN event_type='CASH_REVERSED' THEN -amount_cents
                        ELSE 0 END), 0) AS cash_cents,
                    COALESCE(SUM(CASE
                        WHEN event_type='COST_INCURRED' THEN amount_cents
                        WHEN event_type='COST_REVERSED' THEN -amount_cents
                        ELSE 0 END), 0) AS cost_cents,
                    COALESCE(SUM(CASE
                        WHEN event_type='CASH_RECEIVED' THEN 1
                        WHEN event_type='CASH_REVERSED' THEN -1
                        ELSE 0 END), 0) AS sample_count
                FROM reconciliation_events
                WHERE opportunity_id=?
                """,
                (opportunity,),
            ).fetchone()
        cash_cents = int(row["cash_cents"])
        cost_cents = int(row["cost_cents"])
        samples = int(row["sample_count"])
        if cash_cents < 0 or cost_cents < 0 or samples < 0:
            raise RuntimeError("reconciliation ledger invariant violated")
        cash = cash_cents / 100.0
        cost = cost_cents / 100.0
        return RealizedSummary(opportunity, cash, cost, cash - cost, samples)

    def learning_decision(
        self,
        opportunity_id: object,
        *,
        min_samples_to_scale: int = 3,
        min_realized_profit_to_scale_eur: float = 25.0,
    ) -> RealizedCashDecision:
        summary = self.realized_summary(opportunity_id)
        return decide_from_realized_cash(
            summary.opportunity_id,
            realized_cash_eur=summary.realized_cash_eur,
            reconciled_cost_eur=summary.reconciled_cost_eur,
            sample_count=summary.sample_count,
            min_samples_to_scale=min_samples_to_scale,
            min_realized_profit_to_scale_eur=min_realized_profit_to_scale_eur,
        )
