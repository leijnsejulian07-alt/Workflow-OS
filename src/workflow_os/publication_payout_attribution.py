from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .audit import AuditRevenueLedger
from .publication_provenance import PublicationProvenance, PublicationProvenanceLedger
from .sqlite_lifecycle import managed_connection

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class PublicationPayoutEvidence:
    """Verified provider evidence that one payout event refers to one publication.

    The caller may not supply an opportunity ID. Opportunity identity is recovered
    exclusively through PublicationProvenanceLedger so a payout adapter cannot choose
    which campaign receives realized-cash credit.
    """

    payout_event_id: str
    receipt_id: str
    publication_target: str
    publication_reference: str
    evidence_sha256: str


def _bounded_text(value: object, name: str, *, max_len: int = 300) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > max_len or any(ord(ch) < 32 for ch in cleaned):
        raise ValueError(f"invalid {name}")
    return cleaned


def _digest(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("evidence_sha256 must be a lowercase SHA-256 digest")
    cleaned = value.strip()
    if not _SHA256_RE.fullmatch(cleaned):
        raise ValueError("evidence_sha256 must be a lowercase SHA-256 digest")
    return cleaned


def _load_receipt_identity(
    audit_ledger: AuditRevenueLedger,
    receipt_id: str,
) -> tuple[str, str, str]:
    path = Path(audit_ledger.path)
    if not path.exists() or not path.is_file():
        raise ValueError("audit revenue ledger is unavailable")
    try:
        with managed_connection(sqlite3.connect(str(path), timeout=5.0)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only = ON")
            db.execute("PRAGMA busy_timeout = 5000")
            row = db.execute(
                """SELECT source_platform, external_reference, received_at
                   FROM cash_receipts WHERE receipt_id=?""",
                (receipt_id,),
            ).fetchone()
    except sqlite3.Error as exc:
        raise ValueError("audit revenue ledger is unavailable or malformed") from exc
    if row is None:
        raise ValueError("cash receipt does not exist")
    source_platform = _bounded_text(row["source_platform"], "source_platform", max_len=80)
    external_reference = _bounded_text(row["external_reference"], "external_reference")
    received_at = _bounded_text(row["received_at"], "received_at")
    return source_platform, external_reference, received_at


def attribute_cash_from_publication_evidence(
    *,
    audit_ledger: AuditRevenueLedger,
    provenance_ledger: PublicationProvenanceLedger,
    evidence: PublicationPayoutEvidence,
) -> PublicationProvenance:
    """Attribute received cash through proven publication identity, fail closed.

    The receipt must already exist and its immutable external reference must equal the
    provider payout event ID. The publication must already be confirmed provenance.
    We append immutable payout/publication evidence before attribution; that event has
    no scaling effect by itself, so a crash can safely retry the final attribution.
    """

    if not isinstance(audit_ledger, AuditRevenueLedger):
        raise TypeError("audit_ledger must be AuditRevenueLedger")
    if not isinstance(provenance_ledger, PublicationProvenanceLedger):
        raise TypeError("provenance_ledger must be PublicationProvenanceLedger")
    if not isinstance(evidence, PublicationPayoutEvidence):
        raise TypeError("evidence must be PublicationPayoutEvidence")

    payout_event_id = _bounded_text(evidence.payout_event_id, "payout_event_id")
    receipt_id = _bounded_text(evidence.receipt_id, "receipt_id")
    publication_target = _bounded_text(evidence.publication_target, "publication_target")
    publication_reference = _bounded_text(
        evidence.publication_reference, "publication_reference"
    )
    evidence_sha256 = _digest(evidence.evidence_sha256)

    provenance = provenance_ledger.get_by_reference(publication_target, publication_reference)
    if provenance is None:
        raise ValueError("publication is not proven provenance")

    source_platform, receipt_external_reference, received_at = _load_receipt_identity(
        audit_ledger, receipt_id
    )
    if receipt_external_reference != payout_event_id:
        raise ValueError("cash receipt external reference does not match payout event")

    event_material = f"{source_platform}\n{payout_event_id}".encode("utf-8")
    audit_event_id = "payout-publication:" + hashlib.sha256(event_material).hexdigest()
    audit_ledger.append_event(
        audit_event_id,
        "payout.publication_evidence",
        {
            "source_platform": source_platform,
            "payout_event_id": payout_event_id,
            "receipt_id": receipt_id,
            "publication_target": provenance.publication_target,
            "publication_reference": provenance.publication_reference,
            "publication_side_effect_idempotency_key": provenance.side_effect_idempotency_key,
            "publication_side_effect_request_fingerprint": provenance.side_effect_request_fingerprint,
            "evidence_sha256": evidence_sha256,
        },
        subject_id=provenance.opportunity_id,
        occurred_at=received_at,
    )

    audit_ledger.attribute_cash(receipt_id, provenance.opportunity_id)
    return provenance
