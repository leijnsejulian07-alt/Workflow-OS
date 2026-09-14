from __future__ import annotations

from collections.abc import Iterable

from .adapters.openshorts_hosted import OpenShortsHostedTransport
from .durable_openshorts_worker import (
    DurableOpenShortsExecutionResult,
    execute_prepared_durable_openshorts_job,
)
from .durable_worker import claim_verified_opportunity_job
from .job_queue import JobQueue
from .openshorts_durable_runtime import prepare_verified_durable_openshorts_job
from .openshorts_execution import dispatch_prepared_openshorts
from .side_effects import SideEffectLedger


def run_one_durable_openshorts_job(
    *,
    queue: JobQueue,
    side_effect_ledger: SideEffectLedger,
    worker_id: object,
    now: object,
    webhook_url: str,
    allowed_source_hosts: Iterable[str],
    allowed_webhook_hosts: Iterable[str],
    credential_authority_verified: bool,
    cost_authority_verified: bool,
    transport: OpenShortsHostedTransport,
    api_key: str,
    webhook_secret: str,
    lease_seconds: int = 300,
    captions: bool = True,
    auto_hook: bool = True,
    max_attempts: int = 2,
) -> DurableOpenShortsExecutionResult | None:
    """Claim, prepare, dispatch, and reconcile one durable OpenShorts revenue job.

    Runtime credentials and deployment authority are supplied by the caller and are
    never written into the durable job payload. Preparation failures happen before
    network I/O and are therefore persisted as retry-safe queue failures. Dispatch
    ambiguity is delegated to the existing side-effect-aware durable executor.
    """
    if not isinstance(queue, JobQueue):
        raise TypeError("queue must be JobQueue")
    if not isinstance(side_effect_ledger, SideEffectLedger):
        raise TypeError("side_effect_ledger must be SideEffectLedger")

    verified = claim_verified_opportunity_job(
        queue,
        worker_id=worker_id,
        now=now,
        lease_seconds=lease_seconds,
        allowed_job_types=("produce_and_publish",),
    )
    if verified is None:
        return None

    try:
        prepared = prepare_verified_durable_openshorts_job(
            verified,
            webhook_url=webhook_url,
            allowed_source_hosts=allowed_source_hosts,
            allowed_webhook_hosts=allowed_webhook_hosts,
            credential_authority_verified=credential_authority_verified,
            cost_authority_verified=cost_authority_verified,
            ledger=side_effect_ledger,
            captions=captions,
            auto_hook=auto_hook,
            max_attempts=max_attempts,
        )
    except Exception as exc:
        try:
            queue.fail(
                verified.job.job_id,
                worker_id=worker_id,
                now=now,
                retry_safe=True,
                error="OpenShorts pre-dispatch preparation failed",
            )
        except Exception as transition_exc:
            raise RuntimeError(
                "OpenShorts preparation failed and safe queue transition failed"
            ) from transition_exc
        raise RuntimeError("OpenShorts durable job failed pre-dispatch preparation") from exc

    def _dispatch(bound_prepared):
        return dispatch_prepared_openshorts(
            bound_prepared,
            ledger=side_effect_ledger,
            transport=transport,
            api_key=api_key,
            webhook_secret=webhook_secret,
        )

    return execute_prepared_durable_openshorts_job(
        verified,
        prepared,
        queue=queue,
        worker_id=worker_id,
        now=now,
        side_effect_ledger=side_effect_ledger,
        execute_dispatch=_dispatch,
    )
