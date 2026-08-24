from __future__ import annotations

import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from .reconciliation import ReconciledEvent, RevenueReconciliationLedger
from .sqlite_lifecycle import managed_connection

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class CostEvidence:
    cost_id: str
    opportunity_id: str
    platform: str
    amount_cents: int
    occurred_at: str
    evidence_sha256: str
    external_reference: str


class ResourceCostLedger:
    """Evidence-backed realized cost boundary tied to one known opportunity."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA busy_timeout = 5000")
        return db

    def _init_schema(self) -> None:
        with managed_connection(self._connect()) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS resource_costs (
                    cost_id TEXT PRIMARY KEY,
                    opportunity_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
                    occurred_at TEXT NOT NULL,
                    evidence_sha256 TEXT NOT NULL,
                    external_reference TEXT NOT NULL,
                    UNIQUE(platform, external_reference),
                    FOREIGN KEY(opportunity_id) REFERENCES opportunities(opportunity_id)
                );
                CREATE INDEX IF NOT EXISTS idx_resource_costs_opportunity
                    ON resource_costs(opportunity_id);
                """
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
    def _digest(value: object) -> str:
        if not isinstance(value, str) or not _SHA256_RE.fullmatch(value.strip()):
            raise ValueError("evidence_sha256 must be a lowercase SHA-256 digest")
        return value.strip()

    def record_cost(
        self,
        *,
        cost_id: object,
        opportunity_id: object,
        platform: object,
        amount_eur: object,
        occurred_at: object,
        evidence_sha256: object,
        external_reference: object,
    ) -> CostEvidence:
        candidate = CostEvidence(
            self._identifier(cost_id, "cost_id"),
            self._identifier(opportunity_id, "opportunity_id"),
            self._identifier(platform, "platform", max_len=80),
            self._amount_to_cents(amount_eur),
            self._timestamp(occurred_at),
            self._digest(evidence_sha256),
            self._identifier(external_reference, "external_reference"),
        )
        with managed_connection(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            opportunity = db.execute(
                "SELECT source_platform FROM opportunities WHERE opportunity_id=?",
                (candidate.opportunity_id,),
            ).fetchone()
            if opportunity is None:
                raise ValueError("opportunity does not exist")
            if str(opportunity["source_platform"]) != candidate.platform:
                raise ValueError("cost and opportunity source_platform must match")
            existing = db.execute(
                "SELECT * FROM resource_costs WHERE cost_id=?", (candidate.cost_id,)
            ).fetchone()
            if existing is not None:
                if self._row_matches(existing, candidate):
                    return candidate
                raise ValueError("cost_id already exists with different evidence")
            try:
                db.execute(
                    """INSERT INTO resource_costs(
                        cost_id, opportunity_id, platform, amount_cents, occurred_at,
                        evidence_sha256, external_reference
                    ) VALUES(?,?,?,?,?,?,?)""",
                    (
                        candidate.cost_id,
                        candidate.opportunity_id,
                        candidate.platform,
                        candidate.amount_cents,
                        candidate.occurred_at,
                        candidate.evidence_sha256,
                        candidate.external_reference,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("cost conflicts with an existing external reference") from exc
        return candidate

    @staticmethod
    def _row_matches(row: sqlite3.Row, candidate: CostEvidence) -> bool:
        return (
            row["opportunity_id"] == candidate.opportunity_id
            and row["platform"] == candidate.platform
            and int(row["amount_cents"]) == candidate.amount_cents
            and row["occurred_at"] == candidate.occurred_at
            and row["evidence_sha256"] == candidate.evidence_sha256
            and row["external_reference"] == candidate.external_reference
        )

    def load_cost(self, cost_id: object) -> CostEvidence:
        cost = self._identifier(cost_id, "cost_id")
        with managed_connection(self._connect()) as db:
            row = db.execute(
                """SELECT c.*, o.source_platform AS opportunity_platform
                FROM resource_costs c
                JOIN opportunities o ON o.opportunity_id=c.opportunity_id
                WHERE c.cost_id=?""",
                (cost,),
            ).fetchone()
        if row is None:
            raise ValueError("cost evidence does not exist")
        if row["platform"] != row["opportunity_platform"]:
            raise ValueError("cost and opportunity source_platform must match")
        return CostEvidence(
            row["cost_id"],
            row["opportunity_id"],
            row["platform"],
            int(row["amount_cents"]),
            row["occurred_at"],
            row["evidence_sha256"],
            row["external_reference"],
        )


def promote_verified_cost(
    *,
    cost_ledger: ResourceCostLedger,
    reconciliation_ledger: RevenueReconciliationLedger,
    cost_id: object,
) -> ReconciledEvent:
    """Promote only pre-bound cost evidence into realized-profit scaling truth."""

    if not isinstance(cost_ledger, ResourceCostLedger):
        raise ValueError("cost_ledger must be a ResourceCostLedger")
    if not isinstance(reconciliation_ledger, RevenueReconciliationLedger):
        raise ValueError("reconciliation_ledger must be a RevenueReconciliationLedger")
    cost = cost_ledger.load_cost(cost_id)
    return reconciliation_ledger.record_event(
        platform=cost.platform,
        external_event_id=f"resource-cost:{cost.cost_id}",
        opportunity_id=cost.opportunity_id,
        event_type="COST_INCURRED",
        amount_eur=f"{Decimal(cost.amount_cents) / Decimal(100):.2f}",
        occurred_at=cost.occurred_at,
        evidence_sha256=cost.evidence_sha256,
        currency="EUR",
    )
