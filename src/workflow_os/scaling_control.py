from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .ledger import OpportunityLedger
from .reconciliation import RevenueReconciliationLedger

POLICY_VERSION = "reconciled-scaling-control/1"


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

    A zero-sample opportunity may receive one bounded experiment job so Workflow OS
    can reach first cash. Once reconciled samples exist, realized cash/cost evidence
    is the only source of KEEP/SCALE/PAUSE/KILL authority. This function never
    bypasses upstream eligibility, rights, account, or submission gates.
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
    *,
    limit: int = 50,
    experiment_jobs: int = 1,
    keep_jobs: int = 1,
    scale_jobs: int = 2,
    min_samples_to_scale: int = 3,
    min_realized_profit_to_scale_eur: float = 25.0,
) -> list[dict[str, Any]]:
    """Return only upstream-eligible candidates allowed by realized economics.

    The OpportunityLedger remains the first gate. This layer can only reduce or
    bound scheduling authority; it cannot turn a rejected or ineligible opportunity
    into a candidate. SCALE increases only the bounded job allowance, never rights,
    spend approval, account authorization, or publication authority.
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

        item = dict(candidate)
        item["revenue_control"] = directive.to_dict()
        controlled.append(item)
    return controlled
