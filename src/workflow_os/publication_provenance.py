from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .durable_side_effect_binding import DurableSideEffectBinding
from .side_effects import SideEffectLedger
from .sqlite_lifecycle import managed_connection


@dataclass(frozen=True)
class PublicationProvenance:
    opportunity_id: str
    side_effect_idempotency_key: str
    side_effect_request_fingerprint: str
    publication_target: str
    publication_reference: str


class PublicationProvenanceLedger:
    """Bind a confirmed external publication back to the exact opportunity that produced it.

    Only a SUCCEEDED publish_submission side effect with a stable external reference may
    enter this ledger. This creates durable evidence that later payout/settlement adapters
    can use without guessing which published post belongs to which opportunity.
    """

    def __init__(self, path: str | Path):
        self.path = str(path)
        with managed_connection(self._connect()) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS publication_provenance (
                    side_effect_idempotency_key TEXT PRIMARY KEY,
                    opportunity_id TEXT NOT NULL,
                    side_effect_request_fingerprint TEXT NOT NULL,
                    publication_target TEXT NOT NULL,
                    publication_reference TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(publication_target, publication_reference)
                );
                CREATE INDEX IF NOT EXISTS idx_publication_provenance_opportunity
                    ON publication_provenance(opportunity_id);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=5000")
        return db

    def record_confirmed_publication(
        self,
        binding: DurableSideEffectBinding,
        *,
        side_effect_ledger: SideEffectLedger,
    ) -> PublicationProvenance:
        if not isinstance(binding, DurableSideEffectBinding):
            raise TypeError("binding must be DurableSideEffectBinding")
        if not isinstance(side_effect_ledger, SideEffectLedger):
            raise TypeError("side_effect_ledger must be SideEffectLedger")

        current = side_effect_ledger.get(binding.side_effect_idempotency_key)
        if current is None:
            raise RuntimeError("bound publication side effect is missing")
        if current.request_fingerprint != binding.side_effect_request_fingerprint:
            raise RuntimeError("bound publication side-effect fingerprint changed")
        if current.action != "publish_submission":
            raise RuntimeError("provenance may be recorded only for publication side effects")
        if current.state != "SUCCEEDED":
            raise RuntimeError("publication must be confirmed SUCCEEDED before provenance is recorded")
        if not isinstance(current.external_reference, str) or not current.external_reference.strip():
            raise RuntimeError("confirmed publication requires a stable external reference")

        candidate = PublicationProvenance(
            opportunity_id=binding.opportunity_id,
            side_effect_idempotency_key=current.idempotency_key,
            side_effect_request_fingerprint=current.request_fingerprint,
            publication_target=current.target,
            publication_reference=current.external_reference.strip(),
        )

        with managed_connection(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM publication_provenance WHERE side_effect_idempotency_key=?",
                (candidate.side_effect_idempotency_key,),
            ).fetchone()
            if row:
                existing = self._row(row)
                if existing != candidate:
                    raise ValueError("publication side effect is already bound to different provenance")
                return existing

            duplicate = db.execute(
                """SELECT side_effect_idempotency_key FROM publication_provenance
                   WHERE publication_target=? AND publication_reference=?""",
                (candidate.publication_target, candidate.publication_reference),
            ).fetchone()
            if duplicate:
                raise ValueError("publication reference is already bound to another side effect")

            db.execute(
                """INSERT INTO publication_provenance(
                    side_effect_idempotency_key, opportunity_id,
                    side_effect_request_fingerprint, publication_target, publication_reference
                ) VALUES(?,?,?,?,?)""",
                (
                    candidate.side_effect_idempotency_key,
                    candidate.opportunity_id,
                    candidate.side_effect_request_fingerprint,
                    candidate.publication_target,
                    candidate.publication_reference,
                ),
            )
        return candidate

    def get_by_reference(self, publication_target: str, publication_reference: str) -> PublicationProvenance | None:
        target = publication_target.strip()
        reference = publication_reference.strip()
        if not target or not reference:
            raise ValueError("publication_target and publication_reference are required")
        with managed_connection(self._connect()) as db:
            row = db.execute(
                """SELECT * FROM publication_provenance
                   WHERE publication_target=? AND publication_reference=?""",
                (target, reference),
            ).fetchone()
        return self._row(row) if row else None

    @staticmethod
    def _row(row: sqlite3.Row) -> PublicationProvenance:
        return PublicationProvenance(
            opportunity_id=str(row["opportunity_id"]),
            side_effect_idempotency_key=str(row["side_effect_idempotency_key"]),
            side_effect_request_fingerprint=str(row["side_effect_request_fingerprint"]),
            publication_target=str(row["publication_target"]),
            publication_reference=str(row["publication_reference"]),
        )
