from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .durable_worker import VerifiedLeasedOpportunityJob
from .job_queue import JobQueue, JobRecord
from .production_reservation_pipeline import PreparedProductionSubmission
from .side_effects import SideEffectLedger, SideEffectRecord


@dataclass(frozen=True)
class DurableSideEffectBinding:
    job_id: int
    job_request_fingerprint: str
    opportunity_id: str
    side_effect_idempotency_key: str
    side_effect_request_fingerprint: str


class DurableSideEffectBindingLedger:
    """Persist the exact durable-job -> publication-side-effect identity.

    This ledger contains identifiers/fingerprints only, never credentials. A job may
    be bound once; replay is idempotent only when every immutable identity matches.
    """

    def __init__(self, path: str | Path):
        self.path = str(path)
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS durable_side_effect_bindings(
                    job_id INTEGER PRIMARY KEY,
                    job_request_fingerprint TEXT NOT NULL,
                    opportunity_id TEXT NOT NULL,
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
        prepared: PreparedProductionSubmission,
        *,
        side_effect_ledger: SideEffectLedger,
    ) -> DurableSideEffectBinding:
        if not isinstance(verified_job, VerifiedLeasedOpportunityJob):
            raise TypeError("verified_job must be VerifiedLeasedOpportunityJob")
        if not isinstance(prepared, PreparedProductionSubmission):
            raise TypeError("prepared must be PreparedProductionSubmission")
        if not isinstance(side_effect_ledger, SideEffectLedger):
            raise TypeError("side_effect_ledger must be SideEffectLedger")

        job = verified_job.job
        request = prepared.request
        reserved = prepared.reservation.side_effect
        decision_key = prepared.reservation.decision.idempotency_key
        if request.opportunity_id.strip() != job.opportunity_id:
            raise RuntimeError("production submission opportunity does not match durable job")
        if reserved is None or not prepared.reservation.decision.allowed:
            raise RuntimeError("production submission must already be safely reserved")
        if not decision_key or decision_key != reserved.idempotency_key:
            raise RuntimeError("reserved side-effect idempotency identity is inconsistent")

        current = side_effect_ledger.get(reserved.idempotency_key)
        if current is None:
            raise RuntimeError("reserved side effect is missing from supplied ledger")
        if current.request_fingerprint != reserved.request_fingerprint:
            raise RuntimeError("reserved side-effect fingerprint changed")
        if current.action != "publish_submission":
            raise RuntimeError("durable production job may bind only to publication side effects")
        if current.state not in {"RESERVED", "FAILED_RETRYABLE"}:
            raise RuntimeError("side effect must be retry-authorized when binding")

        candidate = DurableSideEffectBinding(
            job_id=job.job_id,
            job_request_fingerprint=job.request_fingerprint,
            opportunity_id=job.opportunity_id,
            side_effect_idempotency_key=current.idempotency_key,
            side_effect_request_fingerprint=current.request_fingerprint,
        )
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM durable_side_effect_bindings WHERE job_id=?",
                (job.job_id,),
            ).fetchone()
            if row:
                existing = self._row(row)
                if existing != candidate:
                    raise ValueError("durable job is already bound to a different side effect")
                return existing
            other = db.execute(
                "SELECT job_id FROM durable_side_effect_bindings WHERE side_effect_idempotency_key=?",
                (current.idempotency_key,),
            ).fetchone()
            if other:
                raise ValueError("side effect is already bound to another durable job")
            db.execute(
                """INSERT INTO durable_side_effect_bindings(
                    job_id,job_request_fingerprint,opportunity_id,
                    side_effect_idempotency_key,side_effect_request_fingerprint
                ) VALUES(?,?,?,?,?)""",
                (
                    candidate.job_id,
                    candidate.job_request_fingerprint,
                    candidate.opportunity_id,
                    candidate.side_effect_idempotency_key,
                    candidate.side_effect_request_fingerprint,
                ),
            )
        return candidate

    def get(self, job_id: int) -> DurableSideEffectBinding | None:
        if not isinstance(job_id, int) or isinstance(job_id, bool) or job_id < 1:
            raise ValueError("job_id must be a positive integer")
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM durable_side_effect_bindings WHERE job_id=?", (job_id,)
            ).fetchone()
        return self._row(row) if row else None

    @staticmethod
    def _row(row: sqlite3.Row) -> DurableSideEffectBinding:
        return DurableSideEffectBinding(
            job_id=int(row["job_id"]),
            job_request_fingerprint=str(row["job_request_fingerprint"]),
            opportunity_id=str(row["opportunity_id"]),
            side_effect_idempotency_key=str(row["side_effect_idempotency_key"]),
            side_effect_request_fingerprint=str(row["side_effect_request_fingerprint"]),
        )


def reconcile_bound_job_from_side_effect(
    queue: JobQueue,
    binding: DurableSideEffectBinding,
    *,
    worker_id: object,
    now: object,
    side_effect_ledger: SideEffectLedger,
) -> JobRecord:
    """Map only a proven terminal side-effect state back into the leased job.

    SUCCEEDED completes the job. FAILED_RETRYABLE proves no external effect and is
    retry-safe. UNKNOWN makes the job UNKNOWN. RESERVED/EXECUTING are deliberately
    not guessed into a job outcome.
    """

    if not isinstance(queue, JobQueue):
        raise TypeError("queue must be JobQueue")
    if not isinstance(binding, DurableSideEffectBinding):
        raise TypeError("binding must be DurableSideEffectBinding")
    if not isinstance(side_effect_ledger, SideEffectLedger):
        raise TypeError("side_effect_ledger must be SideEffectLedger")

    current = side_effect_ledger.get(binding.side_effect_idempotency_key)
    if current is None:
        raise RuntimeError("bound side effect is missing")
    if current.request_fingerprint != binding.side_effect_request_fingerprint:
        raise RuntimeError("bound side-effect fingerprint changed")

    payload = queue.read_leased_payload(binding.job_id, worker_id=worker_id, now=now)
    if not isinstance(payload, dict) or payload.get("opportunity_id") != binding.opportunity_id:
        raise RuntimeError("bound durable job opportunity changed")

    if current.state == "SUCCEEDED":
        return queue.complete(binding.job_id, worker_id=worker_id, now=now)
    if current.state == "FAILED_RETRYABLE":
        return queue.fail(
            binding.job_id,
            worker_id=worker_id,
            now=now,
            retry_safe=True,
            error="bound publication was proven not applied",
        )
    if current.state == "UNKNOWN":
        return queue.fail(
            binding.job_id,
            worker_id=worker_id,
            now=now,
            retry_safe=False,
            error="bound publication outcome is unknown",
        )
    raise RuntimeError(f"bound side effect is not terminal: {current.state}")
