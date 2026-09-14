from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .job_queue import JobQueue, JobRecord
from .opportunity_snapshot import verify_opportunity_snapshot


_DEFAULT_ALLOWED_JOB_TYPES = frozenset({"produce_and_publish"})


@dataclass(frozen=True)
class VerifiedLeasedOpportunityJob:
    """A live leased job whose persisted payload and opportunity snapshot were verified."""
    job: JobRecord
    payload: dict[str, Any]
    opportunity: dict[str, Any]


def _allowed_types(values: Iterable[str]) -> frozenset[str]:
    allowed: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise ValueError("allowed job types must be strings")
        item = value.strip()
        if not item or len(item) > 100 or any(ord(ch) < 32 for ch in item):
            raise ValueError("invalid allowed job type")
        allowed.add(item)
    if not allowed:
        raise ValueError("at least one allowed job type is required")
    return frozenset(allowed)


def claim_verified_opportunity_job(
    queue: JobQueue,
    *,
    worker_id: object,
    now: object,
    lease_seconds: int = 300,
    allowed_job_types: Iterable[str] = _DEFAULT_ALLOWED_JOB_TYPES,
) -> VerifiedLeasedOpportunityJob | None:
    """Claim one compatible durable job and verify restart-critical identity.

    Job-type filtering happens atomically inside the queue claim so a specialized
    worker cannot lease and poison another worker's job. Validation then happens
    before any production/publication side effect; malformed compatible jobs are
    marked retry-safe and eventually DEAD-lettered after bounded attempts.
    """
    if not isinstance(queue, JobQueue):
        raise TypeError("queue must be JobQueue")
    allowed = _allowed_types(allowed_job_types)
    job = queue.claim(
        worker_id=worker_id,
        now=now,
        lease_seconds=lease_seconds,
        allowed_job_types=allowed,
    )
    if job is None:
        return None

    try:
        if job.job_type not in allowed:
            raise RuntimeError("leased job type is not executable by this worker")

        payload = queue.read_leased_payload(job.job_id, worker_id=worker_id, now=now)
        if not isinstance(payload, dict):
            raise RuntimeError("leased job payload must be an object")
        if payload.get("opportunity_id") != job.opportunity_id:
            raise RuntimeError("leased job opportunity identity mismatch")

        batch = payload.get("batch_fingerprint")
        if (
            not isinstance(batch, str)
            or len(batch) != 64
            or batch.lower() != batch
            or any(ch not in "0123456789abcdef" for ch in batch)
        ):
            raise RuntimeError("leased job batch fingerprint is invalid")

        snapshot = payload.get("opportunity_snapshot")
        snapshot_sha = payload.get("opportunity_snapshot_sha256")
        opportunity = verify_opportunity_snapshot(snapshot, snapshot_sha, job.opportunity_id)

        revenue_control = payload.get("revenue_control")
        if not isinstance(revenue_control, dict):
            raise RuntimeError("leased job revenue control must be an object")
        if revenue_control.get("opportunity_id") != job.opportunity_id:
            raise RuntimeError("leased job revenue-control identity mismatch")
        if revenue_control.get("may_schedule") is not True:
            raise RuntimeError("leased job is no longer represented as schedulable")

        slot = payload.get("batch_slot")
        if not isinstance(slot, int) or isinstance(slot, bool) or slot < 1 or slot > 4:
            raise RuntimeError("leased job batch slot is invalid")

        return VerifiedLeasedOpportunityJob(job=job, payload=payload, opportunity=opportunity)
    except Exception as exc:
        try:
            queue.fail(
                job.job_id,
                worker_id=worker_id,
                now=now,
                retry_safe=True,
                error="pre-execution durable job validation failed",
            )
        except Exception as transition_exc:
            raise RuntimeError("durable job validation failed and safe queue transition failed") from transition_exc
        raise RuntimeError("durable job failed pre-execution verification") from exc
