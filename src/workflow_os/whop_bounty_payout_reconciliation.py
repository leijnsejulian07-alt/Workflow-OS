from __future__ import annotations

from dataclasses import dataclass

from .audit import AuditRevenueLedger
from .reconciliation import ReconciledEvent, RevenueReconciliationLedger
from .reconciliation_attribution import (
    load_attributed_cash_receipt,
    promote_attributed_cash_receipt,
)
from .whop_bounty_payout_attribution import (
    WhopBountyPayoutEvidence,
    attribute_cash_from_whop_bounty_evidence,
)
from .whop_bounty_submission_provenance import (
    WhopBountySubmissionProvenance,
    WhopBountySubmissionProvenanceLedger,
)


@dataclass(frozen=True)
class WhopBountyPayoutReconciliationResult:
    provenance: WhopBountySubmissionProvenance
    reconciled_event: ReconciledEvent


def reconcile_whop_bounty_payout_to_scaling_truth(
    *,
    audit_ledger: AuditRevenueLedger,
    provenance_ledger: WhopBountySubmissionProvenanceLedger,
    reconciliation_ledger: RevenueReconciliationLedger,
    evidence: WhopBountyPayoutEvidence,
    settlement_evidence_sha256: str,
) -> WhopBountyPayoutReconciliationResult:
    """Promote verified Whop bounty received cash into realized-cash truth.

    Submission provenance, payout attribution and settlement reconciliation remain
    separate evidence boundaries. Each write is idempotent so a crash between local
    SQLite ledgers can be retried without changing opportunity identity or duplicating
    realized cash. A caller cannot supply an opportunity ID at any stage.
    """

    if not isinstance(audit_ledger, AuditRevenueLedger):
        raise TypeError("audit_ledger must be AuditRevenueLedger")
    if not isinstance(provenance_ledger, WhopBountySubmissionProvenanceLedger):
        raise TypeError("provenance_ledger must be WhopBountySubmissionProvenanceLedger")
    if not isinstance(reconciliation_ledger, RevenueReconciliationLedger):
        raise TypeError("reconciliation_ledger must be RevenueReconciliationLedger")
    if not isinstance(evidence, WhopBountyPayoutEvidence):
        raise TypeError("evidence must be WhopBountyPayoutEvidence")

    provenance = attribute_cash_from_whop_bounty_evidence(
        audit_ledger=audit_ledger,
        provenance_ledger=provenance_ledger,
        evidence=evidence,
    )

    attributed = load_attributed_cash_receipt(audit_ledger.path, evidence.receipt_id)
    if attributed.opportunity_id != provenance.opportunity_id:
        raise RuntimeError(
            "attributed receipt opportunity does not match Whop bounty submission provenance"
        )

    reconciled = promote_attributed_cash_receipt(
        legacy_db_path=audit_ledger.path,
        reconciliation_ledger=reconciliation_ledger,
        receipt_id=evidence.receipt_id,
        evidence_sha256=settlement_evidence_sha256,
    )
    if reconciled.opportunity_id != provenance.opportunity_id:
        raise RuntimeError(
            "reconciled event opportunity does not match Whop bounty submission provenance"
        )

    return WhopBountyPayoutReconciliationResult(
        provenance=provenance,
        reconciled_event=reconciled,
    )
