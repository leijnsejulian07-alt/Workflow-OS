from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .openshorts_one_shot_worker import run_one_durable_openshorts_job


@dataclass(frozen=True)
class OpenShortsWorkerCycleResult:
    attempted: int
    completed: int
    stopped_on_empty_queue: bool


def run_bounded_openshorts_worker_cycle(*, max_jobs: int = 1, **run_one_kwargs: Any) -> OpenShortsWorkerCycleResult:
    """Process a bounded number of durable OpenShorts jobs.

    This intentionally never spins forever. The caller may invoke the cycle from an
    external scheduler, while the low-storage worker performs at most ``max_jobs``
    sequential jobs and stops immediately when the durable queue is empty.
    """
    if not isinstance(max_jobs, int) or isinstance(max_jobs, bool) or max_jobs < 1 or max_jobs > 4:
        raise ValueError("max_jobs must be an integer between 1 and 4")

    attempted = 0
    completed = 0
    for _ in range(max_jobs):
        result = run_one_durable_openshorts_job(**run_one_kwargs)
        if result is None:
            return OpenShortsWorkerCycleResult(
                attempted=attempted,
                completed=completed,
                stopped_on_empty_queue=True,
            )
        attempted += 1
        if result.job.state == "SUCCEEDED":
            completed += 1

    return OpenShortsWorkerCycleResult(
        attempted=attempted,
        completed=completed,
        stopped_on_empty_queue=False,
    )
