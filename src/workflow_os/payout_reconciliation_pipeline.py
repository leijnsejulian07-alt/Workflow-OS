from __future__ import annotations

from dataclasses import dataclass

from .audit import AuditRevenueLedger
from .publication_payout_attribution import (
    PublicationPayoutEvidence,
    attribute_cash_from_publication_evidence,
)
from .publication_provenance import PublicationProvenance, PublicationProvenanceLedger
from .reconciliation import ReconciledEvent, RevenueReconciliationLedger
from .reconciliation_attribution import (
    load_attributed_cash_receipt,
    promote_attributed_cash_receipt,
)


@dataclass(frozen=True)
class PayoutReconciliationResult:
    provenance: PublicationProvenance
    reconciled_event: ReconciledEvent


def reconcile_publication_payout_to_scaling_truth(
    *,
    audit_ledger: AuditRevenueLedger,
    provenance_ledger: PublicationProvenanceLedger,
    reconciliation_ledger: RevenueReconciliationLedger,
    evidence: PublicationPayoutEvidence,
    settlement_evidence_sha256: str,
) -> PayoutReconciliationResult:
    """Promote one verified publication-backed payout into realized-cash truth.

    The handoff intentionally spans two local SQLite ledgers. Each mutation below is
    idempotent, so a crash between attribution and reconciliation can be retried
    safely without creating duplicate cash or changing opportunity identity.

    Publication evidence and settlement evidence remain separate. A caller cannot
    supply an opportunity ID at either stage.
    """

    if not isinstance(audit_ledger, AuditRevenueLedger):
        raise TypeError("audit_ledger must be AuditRevenueLedger")
    if not isinstance(provenance_ledger, PublicationProvenanceLedger):
        raise TypeError("provenance_ledger must be PublicationProvenanceLedger")
    if not isinstance(reconciliation_ledger, RevenueReconciliationLedger):
        raise TypeError("reconciliation_ledger must be RevenueReconciliationLedger")
    if not isinstance(evidence, PublicationPayoutEvidence):
        raise TypeError("evidence must be PublicationPayoutEvidence")

    provenance = attribute_cash_from_publication_evidence(
        audit_ledger=audit_ledger,
        provenance_ledger=provenance_ledger,
        evidence=evidence,
    )

    attributed = load_attributed_cash_receipt(audit_ledger.path, evidence.receipt_id)
    if attributed.opportunity_id != provenance.opportunity_id:
        raise RuntimeError("attributed receipt opportunity does not match publication provenance")

    reconciled = promote_attributed_cash_receipt(
        legacy_db_path=audit_ledger.path,
        reconciliation_ledger=reconciliation_ledger,
        receipt_id=evidence.receipt_id,
        evidence_sha256=settlement_evidence_sha256,
    )
    if reconciled.opportunity_id != provenance.opportunity_id:
        raise RuntimeError("reconciled event opportunity does not match publication provenance")

    return PayoutReconciliationResult(
        provenance=provenance,
        reconciled_event=reconciled,
    )
