from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .adapters.whop_bounty_submission import WHOP_BOUNTY_SUBMISSION_URL
from .durable_whop_bounty_binding import DurableWhopBountyBinding
from .side_effects import SideEffectLedger
from .sqlite_lifecycle import managed_connection

_SUBMISSION_ID_RE = re.compile(r"^btys_[A-Za-z0-9_-]{3,200}$")


@dataclass(frozen=True)
class WhopBountySubmissionProvenance:
    opportunity_id: str
    bounty_id: str
    side_effect_idempotency_key: str
    side_effect_request_fingerprint: str
    submission_target: str
    submission_reference: str


class WhopBountySubmissionProvenanceLedger:
    """Bind a confirmed Whop workforce submission to the exact opportunity that earned it.

    This ledger records submission identity only. A successful/accepted submission is not
    payout evidence and never proves received cash. Later payout adapters must supply their
    own independently verified payout and receipt evidence before realized-cash attribution.
    """

    def __init__(self, path: str | Path):
        self.path = str(path)
        with managed_connection(self._connect()) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS whop_bounty_submission_provenance (
                    side_effect_idempotency_key TEXT PRIMARY KEY,
                    opportunity_id TEXT NOT NULL,
                    bounty_id TEXT NOT NULL,
                    side_effect_request_fingerprint TEXT NOT NULL,
                    submission_target TEXT NOT NULL,
                    submission_reference TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(submission_target, submission_reference)
                );
                CREATE INDEX IF NOT EXISTS idx_whop_bounty_submission_provenance_opportunity
                    ON whop_bounty_submission_provenance(opportunity_id);
                CREATE INDEX IF NOT EXISTS idx_whop_bounty_submission_provenance_bounty
                    ON whop_bounty_submission_provenance(bounty_id);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=5000")
        return db

    def record_confirmed_submission(
        self,
        binding: DurableWhopBountyBinding,
        *,
        side_effect_ledger: SideEffectLedger,
    ) -> WhopBountySubmissionProvenance:
        if not isinstance(binding, DurableWhopBountyBinding):
            raise TypeError("binding must be DurableWhopBountyBinding")
        if not isinstance(side_effect_ledger, SideEffectLedger):
            raise TypeError("side_effect_ledger must be SideEffectLedger")

        current = side_effect_ledger.get(binding.side_effect_idempotency_key)
        if current is None:
            raise RuntimeError("bound Whop bounty side effect is missing")
        if current.request_fingerprint != binding.side_effect_request_fingerprint:
            raise RuntimeError("bound Whop bounty side-effect fingerprint changed")
        if current.action != "submit_whop_bounty" or current.target != WHOP_BOUNTY_SUBMISSION_URL:
            raise RuntimeError("provenance may be recorded only for Whop bounty submissions")
        if current.state != "SUCCEEDED":
            raise RuntimeError("Whop bounty submission must be confirmed SUCCEEDED before provenance")
        if not isinstance(current.external_reference, str):
            raise RuntimeError("confirmed Whop bounty submission requires a stable submission reference")
        submission_reference = current.external_reference.strip()
        if not _SUBMISSION_ID_RE.fullmatch(submission_reference):
            raise RuntimeError("confirmed Whop bounty submission reference is malformed")

        candidate = WhopBountySubmissionProvenance(
            opportunity_id=binding.opportunity_id,
            bounty_id=binding.bounty_id,
            side_effect_idempotency_key=current.idempotency_key,
            side_effect_request_fingerprint=current.request_fingerprint,
            submission_target=current.target,
            submission_reference=submission_reference,
        )

        with managed_connection(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM whop_bounty_submission_provenance WHERE side_effect_idempotency_key=?",
                (candidate.side_effect_idempotency_key,),
            ).fetchone()
            if row:
                existing = self._row(row)
                if existing != candidate:
                    raise ValueError("Whop bounty side effect is already bound to different provenance")
                return existing

            duplicate = db.execute(
                """SELECT side_effect_idempotency_key FROM whop_bounty_submission_provenance
                   WHERE submission_target=? AND submission_reference=?""",
                (candidate.submission_target, candidate.submission_reference),
            ).fetchone()
            if duplicate:
                raise ValueError("Whop bounty submission reference is already bound to another side effect")

            db.execute(
                """INSERT INTO whop_bounty_submission_provenance(
                    side_effect_idempotency_key, opportunity_id, bounty_id,
                    side_effect_request_fingerprint, submission_target, submission_reference
                ) VALUES(?,?,?,?,?,?)""",
                (
                    candidate.side_effect_idempotency_key,
                    candidate.opportunity_id,
                    candidate.bounty_id,
                    candidate.side_effect_request_fingerprint,
                    candidate.submission_target,
                    candidate.submission_reference,
                ),
            )
        return candidate

    def get_by_reference(
        self,
        submission_reference: str,
        *,
        submission_target: str = WHOP_BOUNTY_SUBMISSION_URL,
    ) -> WhopBountySubmissionProvenance | None:
        if not isinstance(submission_reference, str):
            raise ValueError("submission_reference must be a string")
        reference = submission_reference.strip()
        if not _SUBMISSION_ID_RE.fullmatch(reference):
            raise ValueError("submission_reference is malformed")
        if submission_target != WHOP_BOUNTY_SUBMISSION_URL:
            raise ValueError("submission_target must be the official Whop bounty endpoint")
        with managed_connection(self._connect()) as db:
            row = db.execute(
                """SELECT * FROM whop_bounty_submission_provenance
                   WHERE submission_target=? AND submission_reference=?""",
                (submission_target, reference),
            ).fetchone()
        return self._row(row) if row else None

    @staticmethod
    def _row(row: sqlite3.Row) -> WhopBountySubmissionProvenance:
        return WhopBountySubmissionProvenance(
            opportunity_id=str(row["opportunity_id"]),
            bounty_id=str(row["bounty_id"]),
            side_effect_idempotency_key=str(row["side_effect_idempotency_key"]),
            side_effect_request_fingerprint=str(row["side_effect_request_fingerprint"]),
            submission_target=str(row["submission_target"]),
            submission_reference=str(row["submission_reference"]),
        )
