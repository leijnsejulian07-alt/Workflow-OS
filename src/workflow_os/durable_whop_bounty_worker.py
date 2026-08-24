from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .adapters.whop_bounty_execution import WhopBountyReservation
from .durable_whop_bounty_binding import (
    DurableWhopBountyBinding,
    DurableWhopBountyBindingLedger,
)
from .durable_worker import VerifiedLeasedOpportunityJob
from .job_queue import JobQueue, JobRecord
from .side_effects import SideEffectLedger, SideEffectRecord


@dataclass(frozen=True)
class DurableWhopBountyExecutionResult:
    """Persisted result after one durable Whop workforce submission attempt."""

    job: JobRecord
    binding: DurableWhopBountyBinding
    side_effect: SideEffectRecord


def _reconcile_whop_job(
    queue: JobQueue,
    binding: DurableWhopBountyBinding,
    *,
    worker_id: object,
    now: object,
    side_effect_ledger: SideEffectLedger,
) -> DurableWhopBountyExecutionResult:
    current = side_effect_ledger.get(binding.side_effect_idempotency_key)
    if current is None:
        queue.fail(
            binding.job_id,
            worker_id=worker_id,
            now=now,
            retry_safe=False,
            error="bound Whop bounty side effect disappeared after binding",
        )
        raise RuntimeError("bound Whop bounty side effect disappeared after binding")
    if current.request_fingerprint != binding.side_effect_request_fingerprint:
        queue.fail(
            binding.job_id,
            worker_id=worker_id,
            now=now,
            retry_safe=False,
            error="bound Whop bounty side-effect fingerprint changed",
        )
        raise RuntimeError("bound Whop bounty side-effect fingerprint changed")

    if current.state == "SUCCEEDED":
        job = queue.complete(binding.job_id, worker_id=worker_id, now=now)
        return DurableWhopBountyExecutionResult(job=job, binding=binding, side_effect=current)

    if current.state == "FAILED_RETRYABLE":
        job = queue.fail(
            binding.job_id,
            worker_id=worker_id,
            now=now,
            retry_safe=True,
            error="Whop bounty submission was proven not applied",
        )
        return DurableWhopBountyExecutionResult(job=job, binding=binding, side_effect=current)

    if current.state == "UNKNOWN":
        job = queue.fail(
            binding.job_id,
            worker_id=worker_id,
            now=now,
            retry_safe=False,
            error="Whop bounty submission outcome is ambiguous",
        )
        return DurableWhopBountyExecutionResult(job=job, binding=binding, side_effect=current)

    if current.state == "RESERVED":
        job = queue.fail(
            binding.job_id,
            worker_id=worker_id,
            now=now,
            retry_safe=True,
            error="Whop bounty attempt ended before external execution began",
        )
        return DurableWhopBountyExecutionResult(job=job, binding=binding, side_effect=current)

    if current.state == "EXECUTING":
        job = queue.fail(
            binding.job_id,
            worker_id=worker_id,
            now=now,
            retry_safe=False,
            error="Whop bounty attempt ended without terminal side-effect evidence",
        )
        return DurableWhopBountyExecutionResult(job=job, binding=binding, side_effect=current)

    queue.fail(
        binding.job_id,
        worker_id=worker_id,
        now=now,
        retry_safe=False,
        error="Whop bounty side effect reached an unsupported persisted state",
    )
    raise RuntimeError(f"unsupported Whop bounty side-effect state: {current.state}")


def execute_bound_whop_bounty_job(
    verified_job: VerifiedLeasedOpportunityJob,
    reservation: WhopBountyReservation,
    *,
    queue: JobQueue,
    worker_id: object,
    now: object,
    binding_ledger: DurableWhopBountyBindingLedger,
    side_effect_ledger: SideEffectLedger,
    execute_submission: Callable[[WhopBountyReservation], SideEffectRecord],
) -> DurableWhopBountyExecutionResult:
    """Execute one leased Whop workforce job and persist a safe queue outcome.

    A live queue lease and the immutable job-to-submission binding are verified
    before the executor is called. The SideEffectLedger remains authoritative for
    whether external execution began and whether the result was confirmed. Worker
    exceptions therefore cannot create a second blind retry path.
    """

    if not isinstance(verified_job, VerifiedLeasedOpportunityJob):
        raise TypeError("verified_job must be VerifiedLeasedOpportunityJob")
    if not isinstance(reservation, WhopBountyReservation):
        raise TypeError("reservation must be WhopBountyReservation")
    if not isinstance(queue, JobQueue):
        raise TypeError("queue must be JobQueue")
    if not isinstance(binding_ledger, DurableWhopBountyBindingLedger):
        raise TypeError("binding_ledger must be DurableWhopBountyBindingLedger")
    if not isinstance(side_effect_ledger, SideEffectLedger):
        raise TypeError("side_effect_ledger must be SideEffectLedger")
    if not callable(execute_submission):
        raise TypeError("execute_submission must be callable")

    queue.read_leased_payload(verified_job.job.job_id, worker_id=worker_id, now=now)
    binding = binding_ledger.bind(
        verified_job,
        reservation,
        side_effect_ledger=side_effect_ledger,
    )

    try:
        returned = execute_submission(reservation)
        if not isinstance(returned, SideEffectRecord):
            raise TypeError("Whop bounty executor must return SideEffectRecord")
        if returned.idempotency_key != binding.side_effect_idempotency_key:
            raise RuntimeError("Whop bounty executor returned a different side effect")
        if returned.request_fingerprint != binding.side_effect_request_fingerprint:
            raise RuntimeError("Whop bounty executor returned a different side-effect fingerprint")
    except Exception:
        return _reconcile_whop_job(
            queue,
            binding,
            worker_id=worker_id,
            now=now,
            side_effect_ledger=side_effect_ledger,
        )

    return _reconcile_whop_job(
        queue,
        binding,
        worker_id=worker_id,
        now=now,
        side_effect_ledger=side_effect_ledger,
    )
