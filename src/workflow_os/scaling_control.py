from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .experiment_ledger import ExperimentLedger
from .ledger import OpportunityLedger
from .reconciliation import RevenueReconciliationLedger

POLICY_VERSION = "reconciled-scaling-control/2"


@dataclass(frozen=True)
class ScalingDirective:
    opportunity_id: str
    action: str
    may_schedule: bool
    max_new_jobs: int
    reasons: tuple[str, ...]
    realized_cash_eur: float
    reconciled_cost_eur: float
    realized_profit_eur: float
    sample_count: int
    policy_version: str = POLICY_VERSION

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["reasons"] = list(self.reasons)
        return data


def scaling_directive(
    reconciliation: RevenueReconciliationLedger,
    opportunity_id: object,
    *,
    experiment_jobs: int = 1,
    keep_jobs: int = 1,
    scale_jobs: int = 2,
    min_samples_to_scale: int = 3,
    min_realized_profit_to_scale_eur: float = 25.0,
) -> ScalingDirective:
    """Translate reconciled economics into a bounded scheduling directive.

    This is a pure policy decision. Persistent first-experiment enforcement occurs
    at the controlled-queue boundary through ExperimentLedger.
    """
    for name, value, minimum in (
        ("experiment_jobs", experiment_jobs, 1),
        ("keep_jobs", keep_jobs, 1),
        ("scale_jobs", scale_jobs, 1),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum or value > 4:
            raise ValueError(f"{name} must be an integer between {minimum} and 4")
    if scale_jobs < keep_jobs:
        raise ValueError("scale_jobs must be greater than or equal to keep_jobs")

    summary = reconciliation.realized_summary(opportunity_id)
    if summary.sample_count == 0:
        return ScalingDirective(
            opportunity_id=summary.opportunity_id,
            action="EXPERIMENT",
            may_schedule=True,
            max_new_jobs=experiment_jobs,
            reasons=("NO_RECONCILED_SAMPLE_BOUNDED_EXPERIMENT",),
            realized_cash_eur=summary.realized_cash_eur,
            reconciled_cost_eur=summary.reconciled_cost_eur,
            realized_profit_eur=summary.realized_profit_eur,
            sample_count=summary.sample_count,
        )

    decision = reconciliation.learning_decision(
        summary.opportunity_id,
        min_samples_to_scale=min_samples_to_scale,
        min_realized_profit_to_scale_eur=min_realized_profit_to_scale_eur,
    )
    if decision.action == "KEEP":
        max_new_jobs = keep_jobs
        may_schedule = True
    elif decision.action == "SCALE":
        max_new_jobs = scale_jobs
        may_schedule = True
    elif decision.action in {"PAUSE", "KILL"}:
        max_new_jobs = 0
        may_schedule = False
    else:
        raise RuntimeError("unsupported realized-cash action")

    return ScalingDirective(
        opportunity_id=decision.opportunity_id,
        action=decision.action,
        may_schedule=may_schedule,
        max_new_jobs=max_new_jobs,
        reasons=decision.reasons,
        realized_cash_eur=decision.realized_cash_eur,
        reconciled_cost_eur=decision.reconciled_cost_eur,
        realized_profit_eur=decision.realized_profit_eur,
        sample_count=decision.sample_count,
    )


def revenue_controlled_queue_candidates(
    opportunities: OpportunityLedger,
    reconciliation: RevenueReconciliationLedger,
    experiments: ExperimentLedger,
    *,
    reserved_at: str,
    limit: int = 50,
    experiment_jobs: int = 1,
    keep_jobs: int = 1,
    scale_jobs: int = 2,
    min_samples_to_scale: int = 3,
    min_realized_profit_to_scale_eur: float = 25.0,
) -> list[dict[str, Any]]:
    """Return upstream-eligible candidates allowed by realized economics.

    A zero-sample opportunity is persisted before it is returned as EXPERIMENT.
    Subsequent scheduler runs therefore cannot create another first-experiment
    batch while settlement evidence is still absent.
    """
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")

    candidates = opportunities.queue_candidates(limit=limit)
    controlled: list[dict[str, Any]] = []
    for candidate in candidates:
        opportunity_id = candidate.get("opportunity_id")
        if not isinstance(opportunity_id, str) or not opportunity_id.strip():
            raise RuntimeError("queue candidate is missing a valid opportunity_id")
        if candidate.get("decision") != "ACCEPT" or candidate.get("eligible_for_queue") is not True:
            raise RuntimeError("OpportunityLedger returned a non-eligible queue candidate")

        directive = scaling_directive(
            reconciliation,
            opportunity_id,
            experiment_jobs=experiment_jobs,
            keep_jobs=keep_jobs,
            scale_jobs=scale_jobs,
            min_samples_to_scale=min_samples_to_scale,
            min_realized_profit_to_scale_eur=min_realized_profit_to_scale_eur,
        )
        if not directive.may_schedule:
            continue

        if directive.action == "EXPERIMENT":
            if not experiments.may_reserve_first_experiment(opportunity_id):
                continue
            experiments.reserve_first_experiment(
                opportunity_id=opportunity_id,
                experiment_key=f"{POLICY_VERSION}:{opportunity_id}",
                reserved_at=reserved_at,
            )

        item = dict(candidate)
        item["revenue_control"] = directive.to_dict()
        controlled.append(item)
    return controlled
