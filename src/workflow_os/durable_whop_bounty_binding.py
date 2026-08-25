from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .adapters.whop_bounty_execution import WhopBountyReservation
from .adapters.whop_bounty_submission import WHOP_BOUNTY_SUBMISSION_URL
from .durable_worker import VerifiedLeasedOpportunityJob
from .side_effects import SideEffectLedger
from .sqlite_lifecycle import managed_connection


@dataclass(frozen=True)
class DurableWhopBountyBinding:
    job_id: int
    job_request_fingerprint: str
    opportunity_id: str
    bounty_id: str
    side_effect_idempotency_key: str
    side_effect_request_fingerprint: str


class DurableWhopBountyBindingLedger:
    """Bind one verified durable job to exactly one Whop workforce submission.

    The binding stores identifiers and fingerprints only. Credentials and deliverable
    secrets are never persisted here. A replay is idempotent only when every immutable
    identity matches the original binding.
    """

    def __init__(self, path: str | Path):
        self.path = str(path)
        with managed_connection(self._connect()) as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS durable_whop_bounty_bindings(
                    job_id INTEGER PRIMARY KEY,
                    job_request_fingerprint TEXT NOT NULL,
                    opportunity_id TEXT NOT NULL,
                    bounty_id TEXT NOT NULL,
                    side_effect_idempotency_key TEXT NOT NULL UNIQUE,
                    side_effect_request_fingerprint TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )"""
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=5000")
        return db

    def bind(
        self,
        verified_job: VerifiedLeasedOpportunityJob,
        reservation: WhopBountyReservation,
        *,
        side_effect_ledger: SideEffectLedger,
    ) -> DurableWhopBountyBinding:
        if not isinstance(verified_job, VerifiedLeasedOpportunityJob):
            raise TypeError("verified_job must be VerifiedLeasedOpportunityJob")
        if not isinstance(reservation, WhopBountyReservation):
            raise TypeError("reservation must be WhopBountyReservation")
        if not isinstance(side_effect_ledger, SideEffectLedger):
            raise TypeError("side_effect_ledger must be SideEffectLedger")

        job = verified_job.job
        opportunity = verified_job.opportunity
        if job.job_type != "produce_and_publish":
            raise RuntimeError("Whop bounty binding requires a produce_and_publish job")
        if opportunity.get("opportunity_id") != job.opportunity_id:
            raise RuntimeError("verified opportunity identity does not match durable job")
        if opportunity.get("source_platform") != "whop_bounties":
            raise RuntimeError("durable job is not a Whop Bounties opportunity")
        if opportunity.get("campaign_id") != reservation.bounty_id:
            raise RuntimeError("Whop bounty reservation does not match opportunity campaign")
        if opportunity.get("bounty_type") != "workforce":
            raise RuntimeError("only workforce bounties have verified worker submission authority")
        if opportunity.get("machine_submission_verified") is not True:
            raise RuntimeError("Whop workforce machine submission is not verified")

        current = side_effect_ledger.get(reservation.idempotency_key)
        if current is None:
            raise RuntimeError("Whop bounty reservation is missing from side-effect ledger")
        if current.idempotency_key != reservation.side_effect.idempotency_key:
            raise RuntimeError("Whop bounty reservation idempotency identity changed")
        if current.request_fingerprint != reservation.side_effect.request_fingerprint:
            raise RuntimeError("Whop bounty reservation fingerprint changed")
        if current.action != "submit_whop_bounty" or current.target != WHOP_BOUNTY_SUBMISSION_URL:
            raise RuntimeError("Whop bounty reservation is bound to the wrong side effect")
        if current.state not in {"RESERVED", "FAILED_RETRYABLE"}:
            raise RuntimeError("Whop bounty side effect is not retry-authorized for binding")

        candidate = DurableWhopBountyBinding(
            job_id=job.job_id,
            job_request_fingerprint=job.request_fingerprint,
            opportunity_id=job.opportunity_id,
            bounty_id=reservation.bounty_id,
            side_effect_idempotency_key=current.idempotency_key,
            side_effect_request_fingerprint=current.request_fingerprint,
        )
        with managed_connection(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM durable_whop_bounty_bindings WHERE job_id=?",
                (job.job_id,),
            ).fetchone()
            if row:
                existing = self._row(row)
                if existing != candidate:
                    raise ValueError("durable job is already bound to a different Whop bounty side effect")
                return existing
            other = db.execute(
                "SELECT job_id FROM durable_whop_bounty_bindings WHERE side_effect_idempotency_key=?",
                (current.idempotency_key,),
            ).fetchone()
            if other:
                raise ValueError("Whop bounty side effect is already bound to another durable job")
            db.execute(
                """INSERT INTO durable_whop_bounty_bindings(
                    job_id,job_request_fingerprint,opportunity_id,bounty_id,
                    side_effect_idempotency_key,side_effect_request_fingerprint
                ) VALUES(?,?,?,?,?,?)""",
                (
                    candidate.job_id,
                    candidate.job_request_fingerprint,
                    candidate.opportunity_id,
                    candidate.bounty_id,
                    candidate.side_effect_idempotency_key,
                    candidate.side_effect_request_fingerprint,
                ),
            )
        return candidate

    def get(self, job_id: int) -> DurableWhopBountyBinding | None:
        if not isinstance(job_id, int) or isinstance(job_id, bool) or job_id < 1:
            raise ValueError("job_id must be a positive integer")
        with managed_connection(self._connect()) as db:
            row = db.execute(
                "SELECT * FROM durable_whop_bounty_bindings WHERE job_id=?",
                (job_id,),
            ).fetchone()
        return self._row(row) if row else None

    @staticmethod
    def _row(row: sqlite3.Row) -> DurableWhopBountyBinding:
        return DurableWhopBountyBinding(
            job_id=int(row["job_id"]),
            job_request_fingerprint=str(row["job_request_fingerprint"]),
            opportunity_id=str(row["opportunity_id"]),
            bounty_id=str(row["bounty_id"]),
            side_effect_idempotency_key=str(row["side_effect_idempotency_key"]),
            side_effect_request_fingerprint=str(row["side_effect_request_fingerprint"]),
        )
