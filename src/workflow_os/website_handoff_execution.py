from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Callable, Literal

from .side_effects import SideEffectLedger, SideEffectRecord
from .sqlite_lifecycle import managed_connection
from .website_fulfillment_gate import WebsiteScopeSnapshot
from .website_handoff_reservation import WebsiteHandoffReservation
from .website_static_build import WebsiteBuildArtifact


@dataclass(frozen=True)
class WebsiteHandoffAttemptResult:
    outcome: Literal["APPLIED", "NOT_APPLIED", "UNKNOWN"]
    external_reference: str | None = None


@dataclass(frozen=True)
class WebsiteHandoffReconciliationResult:
    outcome: Literal["FOUND_APPLIED", "PROVEN_NOT_APPLIED", "STILL_UNKNOWN"]
    external_reference: str | None = None


@dataclass(frozen=True)
class WebsiteDeliveryProvenance:
    opportunity_id: str
    scope_sha256: str
    manifest_sha256: str
    side_effect_idempotency_key: str
    side_effect_request_fingerprint: str
    delivery_target: str
    delivery_reference: str


class WebsiteDeliveryProvenanceLedger:
    """Persist immutable evidence for a confirmed customer handoff.

    A confirmed delivery is not received-cash evidence and does not affect scaling.
    It only binds the exact built artifact to a stable customer-controlled handoff
    reference after the shared SideEffectLedger confirms success.
    """

    def __init__(self, path: str | Path):
        self.path = str(path)
        with managed_connection(self._connect()) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS website_delivery_provenance (
                    side_effect_idempotency_key TEXT PRIMARY KEY,
                    opportunity_id TEXT NOT NULL,
                    scope_sha256 TEXT NOT NULL,
                    manifest_sha256 TEXT NOT NULL,
                    side_effect_request_fingerprint TEXT NOT NULL,
                    delivery_target TEXT NOT NULL,
                    delivery_reference TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(delivery_target, delivery_reference)
                );
                CREATE INDEX IF NOT EXISTS idx_website_delivery_opportunity
                    ON website_delivery_provenance(opportunity_id);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=5000")
        return db

    def record_confirmed_delivery(
        self,
        snapshot: WebsiteScopeSnapshot,
        artifact: WebsiteBuildArtifact,
        reservation: WebsiteHandoffReservation,
        *,
        side_effect_ledger: SideEffectLedger,
    ) -> WebsiteDeliveryProvenance:
        if reservation.side_effect is None:
            raise RuntimeError("handoff reservation has no side effect")
        if artifact.opportunity_id != snapshot.opportunity_id or artifact.scope_sha256 != snapshot.snapshot_sha256:
            raise ValueError("website artifact identity mismatch")

        current = side_effect_ledger.get(reservation.idempotency_key)
        if current is None:
            raise RuntimeError("website handoff side effect is missing")
        if current.action != "WEBSITE_HANDOFF":
            raise RuntimeError("delivery provenance requires WEBSITE_HANDOFF side effect")
        if current.request_fingerprint != reservation.side_effect.request_fingerprint:
            raise RuntimeError("website handoff side-effect fingerprint changed")
        if current.state != "SUCCEEDED":
            raise RuntimeError("website handoff must be confirmed SUCCEEDED before provenance")
        reference = current.external_reference.strip() if isinstance(current.external_reference, str) else ""
        if not reference:
            raise RuntimeError("confirmed website handoff requires stable external reference")

        candidate = WebsiteDeliveryProvenance(
            opportunity_id=snapshot.opportunity_id,
            scope_sha256=snapshot.snapshot_sha256,
            manifest_sha256=artifact.manifest_sha256,
            side_effect_idempotency_key=current.idempotency_key,
            side_effect_request_fingerprint=current.request_fingerprint,
            delivery_target=current.target,
            delivery_reference=reference,
        )

        with managed_connection(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM website_delivery_provenance WHERE side_effect_idempotency_key=?",
                (candidate.side_effect_idempotency_key,),
            ).fetchone()
            if row:
                existing = self._row(row)
                if existing != candidate:
                    raise ValueError("website handoff is already bound to different provenance")
                return existing
            duplicate = db.execute(
                "SELECT side_effect_idempotency_key FROM website_delivery_provenance WHERE delivery_target=? AND delivery_reference=?",
                (candidate.delivery_target, candidate.delivery_reference),
            ).fetchone()
            if duplicate:
                raise ValueError("delivery reference is already bound to another handoff")
            db.execute(
                """INSERT INTO website_delivery_provenance(
                    side_effect_idempotency_key, opportunity_id, scope_sha256,
                    manifest_sha256, side_effect_request_fingerprint,
                    delivery_target, delivery_reference
                ) VALUES(?,?,?,?,?,?,?)""",
                (
                    candidate.side_effect_idempotency_key,
                    candidate.opportunity_id,
                    candidate.scope_sha256,
                    candidate.manifest_sha256,
                    candidate.side_effect_request_fingerprint,
                    candidate.delivery_target,
                    candidate.delivery_reference,
                ),
            )
        return candidate

    @staticmethod
    def _row(row: sqlite3.Row) -> WebsiteDeliveryProvenance:
        return WebsiteDeliveryProvenance(
            opportunity_id=str(row["opportunity_id"]),
            scope_sha256=str(row["scope_sha256"]),
            manifest_sha256=str(row["manifest_sha256"]),
            side_effect_idempotency_key=str(row["side_effect_idempotency_key"]),
            side_effect_request_fingerprint=str(row["side_effect_request_fingerprint"]),
            delivery_target=str(row["delivery_target"]),
            delivery_reference=str(row["delivery_reference"]),
        )


def execute_reserved_website_handoff(
    reservation: WebsiteHandoffReservation,
    *,
    ledger: SideEffectLedger,
    deliver: Callable[[], WebsiteHandoffAttemptResult],
) -> SideEffectRecord:
    """Execute one reserved handoff using an injected customer-controlled adapter."""
    if reservation.side_effect is None or not reservation.idempotency_key:
        raise RuntimeError("website handoff must be reserved before execution")
    current = ledger.get(reservation.idempotency_key)
    if current is None:
        raise RuntimeError("reserved website handoff side effect is missing")
    if current.action != "WEBSITE_HANDOFF":
        raise RuntimeError("reserved side effect is not a website handoff")
    if current.request_fingerprint != reservation.side_effect.request_fingerprint:
        raise RuntimeError("website handoff reservation fingerprint changed")
    if current.state not in {"RESERVED", "FAILED_RETRYABLE"}:
        raise RuntimeError(f"website handoff is not execution-authorized from state {current.state}")

    ledger.begin_attempt(reservation.idempotency_key)
    try:
        result = deliver()
    except Exception:
        ledger.mark_failed(reservation.idempotency_key, definitely_not_applied=False)
        raise
    if not isinstance(result, WebsiteHandoffAttemptResult):
        ledger.mark_failed(reservation.idempotency_key, definitely_not_applied=False)
        raise TypeError("website handoff adapter returned an invalid result")

    if result.outcome == "APPLIED":
        reference = result.external_reference.strip() if isinstance(result.external_reference, str) else ""
        if not reference:
            ledger.mark_failed(reservation.idempotency_key, definitely_not_applied=False)
            raise ValueError("APPLIED website handoff requires stable external reference")
        return ledger.mark_succeeded(reservation.idempotency_key, external_reference=reference)
    if result.outcome == "NOT_APPLIED":
        if result.external_reference is not None:
            ledger.mark_failed(reservation.idempotency_key, definitely_not_applied=False)
            raise ValueError("NOT_APPLIED website handoff cannot include external reference")
        return ledger.mark_failed(reservation.idempotency_key, definitely_not_applied=True)
    if result.outcome == "UNKNOWN":
        if result.external_reference is not None:
            ledger.mark_failed(reservation.idempotency_key, definitely_not_applied=False)
            raise ValueError("UNKNOWN website handoff cannot include external reference")
        return ledger.mark_failed(reservation.idempotency_key, definitely_not_applied=False)

    ledger.mark_failed(reservation.idempotency_key, definitely_not_applied=False)
    raise ValueError("unsupported website handoff outcome")


def reconcile_unknown_website_handoff(
    *,
    ledger: SideEffectLedger,
    idempotency_key: str,
    reconcile: Callable[[], WebsiteHandoffReconciliationResult],
) -> SideEffectRecord:
    """Resolve UNKNOWN delivery state without dispatching another handoff."""
    current = ledger.get(idempotency_key)
    if current is None:
        raise KeyError(idempotency_key)
    if current.action != "WEBSITE_HANDOFF" or current.state != "UNKNOWN":
        raise RuntimeError("only UNKNOWN website handoffs may be reconciled")
    result = reconcile()
    if not isinstance(result, WebsiteHandoffReconciliationResult):
        raise TypeError("website handoff reconciliation returned invalid result")
    if result.outcome == "FOUND_APPLIED":
        reference = result.external_reference.strip() if isinstance(result.external_reference, str) else ""
        if not reference:
            raise ValueError("FOUND_APPLIED requires stable external reference")
        return ledger.mark_succeeded(idempotency_key, external_reference=reference)
    if result.outcome == "PROVEN_NOT_APPLIED":
        if result.external_reference is not None:
            raise ValueError("PROVEN_NOT_APPLIED cannot include external reference")
        return ledger.reconcile_not_applied(idempotency_key)
    if result.outcome == "STILL_UNKNOWN":
        if result.external_reference is not None:
            raise ValueError("STILL_UNKNOWN cannot include external reference")
        latest = ledger.get(idempotency_key)
        if latest is None:
            raise RuntimeError("website handoff disappeared during reconciliation")
        return latest
    raise ValueError("unsupported website handoff reconciliation outcome")
