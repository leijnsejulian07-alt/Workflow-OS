from __future__ import annotations

from dataclasses import dataclass

from .audit import AuditRevenueLedger
from .reconciliation import RevenueReconciliationLedger
from .scaling_control import ScalingDirective, scaling_directive
from .whop_bounty_payout_attribution import WhopBountyPayoutEvidence
from .whop_bounty_payout_reconciliation import (
    WhopBountyPayoutReconciliationResult,
    reconcile_whop_bounty_payout_to_scaling_truth,
)
from .whop_bounty_submission_provenance import WhopBountySubmissionProvenanceLedger


@dataclass(frozen=True)
class WhopBountySettlementFeedbackResult:
    """One verified payout promoted into realized cash plus the next scheduling decision."""

    payout: WhopBountyPayoutReconciliationResult
    scaling: ScalingDirective


def reconcile_whop_bounty_payout_and_decide_next_action(
    *,
    audit_ledger: AuditRevenueLedger,
    provenance_ledger: WhopBountySubmissionProvenanceLedger,
    reconciliation_ledger: RevenueReconciliationLedger,
    evidence: WhopBountyPayoutEvidence,
    settlement_evidence_sha256: str,
    experiment_jobs: int = 1,
    keep_jobs: int = 1,
    scale_jobs: int = 2,
    min_samples_to_scale: int = 3,
    min_realized_profit_to_scale_eur: float = 25.0,
) -> WhopBountySettlementFeedbackResult:
    """Close the first-cash loop from verified Whop payout evidence to bounded scaling.

    The payout is first attributed and promoted through the existing reconciliation
    boundary. Only the resulting RevenueReconciliationLedger state is then allowed
    to drive KEEP/SCALE/PAUSE/KILL. Estimated or platform-reported revenue never
    enters this path, and no new job is scheduled here.
    """

    payout = reconcile_whop_bounty_payout_to_scaling_truth(
        audit_ledger=audit_ledger,
        provenance_ledger=provenance_ledger,
        reconciliation_ledger=reconciliation_ledger,
        evidence=evidence,
        settlement_evidence_sha256=settlement_evidence_sha256,
    )

    opportunity_id = payout.reconciled_event.opportunity_id
    if payout.provenance.opportunity_id != opportunity_id:
        raise RuntimeError("Whop payout provenance drifted before scaling decision")

    directive = scaling_directive(
        reconciliation_ledger,
        opportunity_id,
        experiment_jobs=experiment_jobs,
        keep_jobs=keep_jobs,
        scale_jobs=scale_jobs,
        min_samples_to_scale=min_samples_to_scale,
        min_realized_profit_to_scale_eur=min_realized_profit_to_scale_eur,
    )
    if directive.opportunity_id != opportunity_id:
        raise RuntimeError("scaling directive identity does not match reconciled Whop payout")

    return WhopBountySettlementFeedbackResult(payout=payout, scaling=directive)
