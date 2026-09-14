from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .durable_worker import VerifiedLeasedOpportunityJob
from .job_queue import JobQueue, JobRecord
from .openshorts_execution import OpenShortsDispatchBinding
from .openshorts_job_preparation import PreparedOpenShortsProcessing
from .side_effects import SideEffectLedger, SideEffectRecord


@dataclass(frozen=True)
class DurableOpenShortsExecutionResult:
    """Persisted queue outcome after one durable OpenShorts dispatch attempt."""

    job: JobRecord
    side_effect: SideEffectRecord


def _reconcile_openshorts_job(
    queue: JobQueue,
    prepared: PreparedOpenShortsProcessing,
    *,
    worker_id: object,
    now: object,
    side_effect_ledger: SideEffectLedger,
) -> DurableOpenShortsExecutionResult:
    current = side_effect_ledger.get(prepared.reservation.idempotency_key)
    if current is None:
        queue.fail(
            prepared.job_id,
            worker_id=worker_id,
            now=now,
            retry_safe=False,
            error="bound OpenShorts side effect disappeared after preparation",
        )
        raise RuntimeError("bound OpenShorts side effect disappeared after preparation")
    if current.request_fingerprint != prepared.reservation.request_fingerprint:
        queue.fail(
            prepared.job_id,
            worker_id=worker_id,
            now=now,
            retry_safe=False,
            error="bound OpenShorts side-effect fingerprint changed",
        )
        raise RuntimeError("bound OpenShorts side-effect fingerprint changed")
    if current.action != "openshorts.process":
        queue.fail(
            prepared.job_id,
            worker_id=worker_id,
            now=now,
            retry_safe=False,
            error="bound side effect is not OpenShorts processing",
        )
        raise RuntimeError("bound side effect is not OpenShorts processing")

    if current.state == "SUCCEEDED":
        job = queue.complete(prepared.job_id, worker_id=worker_id, now=now)
        return DurableOpenShortsExecutionResult(job=job, side_effect=current)

    if current.state == "FAILED_RETRYABLE":
        job = queue.fail(
            prepared.job_id,
            worker_id=worker_id,
            now=now,
            retry_safe=True,
            error="OpenShorts dispatch was proven not applied",
        )
        return DurableOpenShortsExecutionResult(job=job, side_effect=current)

    if current.state == "UNKNOWN":
        job = queue.fail(
            prepared.job_id,
            worker_id=worker_id,
            now=now,
            retry_safe=False,
            error="OpenShorts dispatch outcome is ambiguous",
        )
        return DurableOpenShortsExecutionResult(job=job, side_effect=current)

    if current.state == "RESERVED":
        job = queue.fail(
            prepared.job_id,
            worker_id=worker_id,
            now=now,
            retry_safe=True,
            error="OpenShorts attempt ended before external execution began",
        )
        return DurableOpenShortsExecutionResult(job=job, side_effect=current)

    if current.state == "EXECUTING":
        job = queue.fail(
            prepared.job_id,
            worker_id=worker_id,
            now=now,
            retry_safe=False,
            error="OpenShorts attempt ended without confirmed dispatch evidence",
        )
        return DurableOpenShortsExecutionResult(job=job, side_effect=current)

    queue.fail(
        prepared.job_id,
        worker_id=worker_id,
        now=now,
        retry_safe=False,
        error="OpenShorts side effect reached an unsupported persisted state",
    )
    raise RuntimeError(f"unsupported OpenShorts side-effect state: {current.state}")


def execute_prepared_durable_openshorts_job(
    verified_job: VerifiedLeasedOpportunityJob,
    prepared: PreparedOpenShortsProcessing,
    *,
    queue: JobQueue,
    worker_id: object,
    now: object,
    side_effect_ledger: SideEffectLedger,
    execute_dispatch: Callable[[PreparedOpenShortsProcessing], OpenShortsDispatchBinding],
) -> DurableOpenShortsExecutionResult:
    """Execute a prepared leased OpenShorts job and persist a safe queue outcome.

    The live queue lease, durable job identity, request fingerprint, and side-effect
    reservation are rechecked before the dispatcher is called. The SideEffectLedger
    remains authoritative if the dispatcher raises, so a crash after network I/O can
    never create an automatic blind retry.
    """

    if not isinstance(verified_job, VerifiedLeasedOpportunityJob):
        raise TypeError("verified_job must be VerifiedLeasedOpportunityJob")
    if not isinstance(prepared, PreparedOpenShortsProcessing):
        raise TypeError("prepared must be PreparedOpenShortsProcessing")
    if not isinstance(queue, JobQueue):
        raise TypeError("queue must be JobQueue")
    if not isinstance(side_effect_ledger, SideEffectLedger):
        raise TypeError("side_effect_ledger must be SideEffectLedger")
    if not callable(execute_dispatch):
        raise TypeError("execute_dispatch must be callable")

    if prepared.job_id != verified_job.job.job_id:
        raise RuntimeError("prepared OpenShorts job identity does not match durable lease")
    if prepared.opportunity_id != verified_job.job.opportunity_id:
        raise RuntimeError("prepared OpenShorts opportunity identity does not match durable lease")
    if prepared.job_request_fingerprint != verified_job.job.request_fingerprint:
        raise RuntimeError("prepared OpenShorts request fingerprint does not match durable lease")

    queue.read_leased_payload(verified_job.job.job_id, worker_id=worker_id, now=now)
    current = side_effect_ledger.get(prepared.reservation.idempotency_key)
    if current is None:
        raise RuntimeError("prepared OpenShorts reservation is missing")
    if current.request_fingerprint != prepared.reservation.request_fingerprint:
        raise RuntimeError("prepared OpenShorts reservation fingerprint changed")
    if current.state not in {"RESERVED", "FAILED_RETRYABLE"}:
        return _reconcile_openshorts_job(
            queue,
            prepared,
            worker_id=worker_id,
            now=now,
            side_effect_ledger=side_effect_ledger,
        )

    try:
        returned = execute_dispatch(prepared)
        if not isinstance(returned, OpenShortsDispatchBinding):
            raise TypeError("OpenShorts dispatcher must return OpenShortsDispatchBinding")
        if returned.idempotency_key != prepared.reservation.idempotency_key:
            raise RuntimeError("OpenShorts dispatcher returned a different side effect")
    except Exception:
        return _reconcile_openshorts_job(
            queue,
            prepared,
            worker_id=worker_id,
            now=now,
            side_effect_ledger=side_effect_ledger,
        )

    return _reconcile_openshorts_job(
        queue,
        prepared,
        worker_id=worker_id,
        now=now,
        side_effect_ledger=side_effect_ledger,
    )
