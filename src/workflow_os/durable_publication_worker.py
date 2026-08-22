from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .durable_side_effect_binding import (
    DurableSideEffectBinding,
    DurableSideEffectBindingLedger,
    reconcile_bound_job_from_side_effect,
)
from .durable_worker import VerifiedLeasedOpportunityJob
from .job_queue import JobQueue, JobRecord
from .production_reservation_pipeline import PreparedProductionSubmission
from .side_effects import SideEffectLedger, SideEffectRecord


@dataclass(frozen=True)
class DurablePublicationExecutionResult:
    """Persisted outcome after one durable publication worker attempt."""

    job: JobRecord
    binding: DurableSideEffectBinding
    side_effect: SideEffectRecord


def _reconcile_after_publication_attempt(
    queue: JobQueue,
    binding: DurableSideEffectBinding,
    *,
    worker_id: object,
    now: object,
    side_effect_ledger: SideEffectLedger,
) -> DurablePublicationExecutionResult:
    current = side_effect_ledger.get(binding.side_effect_idempotency_key)
    if current is None:
        # Binding creation proved the side effect existed. Losing it afterwards is
        # storage corruption, so the durable job must not be blindly retried.
        job = queue.fail(
            binding.job_id,
            worker_id=worker_id,
            now=now,
            retry_safe=False,
            error="bound publication side effect disappeared after binding",
        )
        raise RuntimeError("bound publication side effect disappeared after binding")
    if current.request_fingerprint != binding.side_effect_request_fingerprint:
        job = queue.fail(
            binding.job_id,
            worker_id=worker_id,
            now=now,
            retry_safe=False,
            error="bound publication side-effect fingerprint changed",
        )
        raise RuntimeError("bound publication side-effect fingerprint changed")

    if current.state in {"SUCCEEDED", "FAILED_RETRYABLE", "UNKNOWN"}:
        job = reconcile_bound_job_from_side_effect(
            queue,
            binding,
            worker_id=worker_id,
            now=now,
            side_effect_ledger=side_effect_ledger,
        )
        return DurablePublicationExecutionResult(job=job, binding=binding, side_effect=current)

    if current.state == "RESERVED":
        # The authoritative side-effect ledger proves execution never began.
        job = queue.fail(
            binding.job_id,
            worker_id=worker_id,
            now=now,
            retry_safe=True,
            error="publication attempt ended before external execution began",
        )
        return DurablePublicationExecutionResult(job=job, binding=binding, side_effect=current)

    if current.state == "EXECUTING":
        # An external effect may have occurred. Fail closed instead of letting the
        # worker lease expire into a second, independent recovery path.
        job = queue.fail(
            binding.job_id,
            worker_id=worker_id,
            now=now,
            retry_safe=False,
            error="publication attempt ended without terminal side-effect evidence",
        )
        return DurablePublicationExecutionResult(job=job, binding=binding, side_effect=current)

    job = queue.fail(
        binding.job_id,
        worker_id=worker_id,
        now=now,
        retry_safe=False,
        error="publication side effect reached an unsupported persisted state",
    )
    raise RuntimeError(f"unsupported publication side-effect state: {current.state}")


def execute_bound_publication_job(
    verified_job: VerifiedLeasedOpportunityJob,
    prepared: PreparedProductionSubmission,
    *,
    queue: JobQueue,
    worker_id: object,
    now: object,
    binding_ledger: DurableSideEffectBindingLedger,
    side_effect_ledger: SideEffectLedger,
    execute_publication: Callable[[PreparedProductionSubmission], SideEffectRecord],
) -> DurablePublicationExecutionResult:
    """Execute one leased production job and always persist a safe queue outcome.

    The exact job -> publication-side-effect identity is durably bound before the
    executor is invoked. The executor may use an official platform adapter such as
    the existing TikTok Direct Post boundary. Regardless of normal return or raised
    exception, the durable JobQueue is reconciled from SideEffectLedger evidence in
    this call; a started-but-nonterminal publication becomes UNKNOWN rather than
    being left for blind lease-expiry recovery.
    """

    if not isinstance(verified_job, VerifiedLeasedOpportunityJob):
        raise TypeError("verified_job must be VerifiedLeasedOpportunityJob")
    if not isinstance(prepared, PreparedProductionSubmission):
        raise TypeError("prepared must be PreparedProductionSubmission")
    if not isinstance(queue, JobQueue):
        raise TypeError("queue must be JobQueue")
    if not isinstance(binding_ledger, DurableSideEffectBindingLedger):
        raise TypeError("binding_ledger must be DurableSideEffectBindingLedger")
    if not isinstance(side_effect_ledger, SideEffectLedger):
        raise TypeError("side_effect_ledger must be SideEffectLedger")
    if not callable(execute_publication):
        raise TypeError("execute_publication must be callable")

    # Re-read the live lease before binding so a stale worker cannot attach a side
    # effect after its execution authority expired.
    queue.read_leased_payload(verified_job.job.job_id, worker_id=worker_id, now=now)
    binding = binding_ledger.bind(
        verified_job,
        prepared,
        side_effect_ledger=side_effect_ledger,
    )

    try:
        returned = execute_publication(prepared)
        if not isinstance(returned, SideEffectRecord):
            raise TypeError("publication executor must return SideEffectRecord")
        if returned.idempotency_key != binding.side_effect_idempotency_key:
            raise RuntimeError("publication executor returned a different side effect")
        if returned.request_fingerprint != binding.side_effect_request_fingerprint:
            raise RuntimeError("publication executor returned a different side-effect fingerprint")
    except Exception:
        # Do not trust the exception to describe whether the platform was reached.
        # The SideEffectLedger is the sole authority for that fact.
        return _reconcile_after_publication_attempt(
            queue,
            binding,
            worker_id=worker_id,
            now=now,
            side_effect_ledger=side_effect_ledger,
        )

    return _reconcile_after_publication_attempt(
        queue,
        binding,
        worker_id=worker_id,
        now=now,
        side_effect_ledger=side_effect_ledger,
    )
