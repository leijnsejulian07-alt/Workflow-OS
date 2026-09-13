from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .adapters.openshorts_hosted import (
    OpenShortsHostedTransport,
    OpenShortsHostedTransportError,
    verify_openshorts_webhook,
)
from .openshorts_job_preparation import PreparedOpenShortsProcessing
from .side_effects import SideEffectLedger
from .sqlite_lifecycle import managed_connection


@dataclass(frozen=True)
class OpenShortsDispatchBinding:
    idempotency_key: str
    provider_job_id: str
    response_sha256: str


@dataclass(frozen=True)
class OpenShortsTerminalEvidence:
    idempotency_key: str
    provider_job_id: str
    terminal_state: str
    evidence_sha256: str
    source: str


class OpenShortsExecutionEvidenceStore:
    """Immutable terminal render evidence, separate from dispatch acceptance."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        with managed_connection(sqlite3.connect(self.path, timeout=5.0)) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS openshorts_terminal_evidence (
                    idempotency_key TEXT PRIMARY KEY,
                    provider_job_id TEXT NOT NULL,
                    terminal_state TEXT NOT NULL CHECK(terminal_state IN ('COMPLETED','FAILED')),
                    evidence_sha256 TEXT NOT NULL,
                    source TEXT NOT NULL CHECK(source IN ('webhook','status_api')),
                    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE UNIQUE INDEX IF NOT EXISTS ux_openshorts_terminal_job
                ON openshorts_terminal_evidence(provider_job_id);
                """
            )

    def record(self, evidence: OpenShortsTerminalEvidence) -> OpenShortsTerminalEvidence:
        with managed_connection(sqlite3.connect(self.path, timeout=5.0)) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM openshorts_terminal_evidence WHERE idempotency_key=?",
                (evidence.idempotency_key,),
            ).fetchone()
            if row:
                current = _evidence_row(row)
                if current != evidence:
                    raise ValueError("terminal OpenShorts evidence is immutable")
                return current
            try:
                db.execute(
                    "INSERT INTO openshorts_terminal_evidence"
                    "(idempotency_key,provider_job_id,terminal_state,evidence_sha256,source) "
                    "VALUES(?,?,?,?,?)",
                    (evidence.idempotency_key, evidence.provider_job_id,
                     evidence.terminal_state, evidence.evidence_sha256, evidence.source),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("provider job is already bound to terminal evidence") from exc
            return evidence

    def get(self, idempotency_key: str) -> OpenShortsTerminalEvidence | None:
        db = sqlite3.connect(self.path, timeout=5.0)
        db.row_factory = sqlite3.Row
        try:
            row = db.execute(
                "SELECT * FROM openshorts_terminal_evidence WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
        finally:
            db.close()
        return _evidence_row(row) if row else None


def _evidence_row(row: sqlite3.Row) -> OpenShortsTerminalEvidence:
    return OpenShortsTerminalEvidence(
        idempotency_key=str(row["idempotency_key"]),
        provider_job_id=str(row["provider_job_id"]),
        terminal_state=str(row["terminal_state"]),
        evidence_sha256=str(row["evidence_sha256"]),
        source=str(row["source"]),
    )


def _bound_dispatch(ledger: SideEffectLedger, prepared: PreparedOpenShortsProcessing):
    key = prepared.reservation.idempotency_key
    current = ledger.get(key)
    if current is None or current.request_fingerprint != prepared.reservation.request_fingerprint:
        raise RuntimeError("OpenShorts reservation binding is missing or changed")
    if current.action != "openshorts.process":
        raise RuntimeError("side-effect action is not OpenShorts processing")
    return current


def dispatch_prepared_openshorts(
    prepared: PreparedOpenShortsProcessing,
    *,
    ledger: SideEffectLedger,
    transport: OpenShortsHostedTransport,
    api_key: str,
    webhook_secret: str,
) -> OpenShortsDispatchBinding:
    """Dispatch once; ambiguity becomes UNKNOWN and is never blindly retried."""
    if not isinstance(prepared, PreparedOpenShortsProcessing):
        raise TypeError("prepared must be PreparedOpenShortsProcessing")
    current = _bound_dispatch(ledger, prepared)
    if current.state == "SUCCEEDED" and current.external_reference:
        raise RuntimeError("OpenShorts dispatch is already durably bound")
    ledger.begin_attempt(current.idempotency_key)
    try:
        result = transport.process_video(
            api_key=api_key,
            source_url=prepared.source_url,
            webhook_url=prepared.webhook_url,
            webhook_secret=webhook_secret,
            captions=prepared.captions,
            auto_hook=prepared.auto_hook,
        )
    except ValueError:
        ledger.mark_failed(current.idempotency_key, definitely_not_applied=True)
        raise
    except OpenShortsHostedTransportError:
        ledger.mark_failed(current.idempotency_key, definitely_not_applied=False)
        raise

    try:
        ledger.mark_succeeded(current.idempotency_key, external_reference=result.job_id)
    except Exception:
        latest = ledger.get(current.idempotency_key)
        if latest is not None and latest.state == "EXECUTING":
            ledger.mark_failed(current.idempotency_key, definitely_not_applied=False)
        raise
    return OpenShortsDispatchBinding(current.idempotency_key, result.job_id, result.response_sha256)


def record_terminal_webhook(
    *,
    ledger: SideEffectLedger,
    evidence_store: OpenShortsExecutionEvidenceStore,
    idempotency_key: str,
    body: bytes,
    signature_header: str,
    webhook_secret: str,
) -> OpenShortsTerminalEvidence:
    event = verify_openshorts_webhook(
        body=body, signature_header=signature_header, webhook_secret=webhook_secret
    )
    record = ledger.get(idempotency_key)
    if record is None or record.state != "SUCCEEDED" or record.external_reference != event.job_id:
        raise RuntimeError("terminal webhook is not bound to a confirmed OpenShorts dispatch")
    terminal = "COMPLETED" if event.event == "job.completed" else "FAILED"
    return evidence_store.record(OpenShortsTerminalEvidence(
        idempotency_key=idempotency_key,
        provider_job_id=event.job_id,
        terminal_state=terminal,
        evidence_sha256=event.body_sha256,
        source="webhook",
    ))


def reconcile_terminal_status(
    *,
    ledger: SideEffectLedger,
    evidence_store: OpenShortsExecutionEvidenceStore,
    idempotency_key: str,
    transport: OpenShortsHostedTransport,
    api_key: str,
) -> OpenShortsTerminalEvidence | None:
    record = ledger.get(idempotency_key)
    if record is None or record.state != "SUCCEEDED" or not record.external_reference:
        raise RuntimeError("status reconciliation requires a confirmed provider job binding")
    payload = transport.get_status(api_key=api_key, job_id=record.external_reference)
    payload_job_id = payload.get("job_id")
    if payload_job_id is not None and str(payload_job_id).strip() != record.external_reference:
        raise OpenShortsHostedTransportError("OpenShorts status job id does not match durable binding")
    status = str(payload.get("status") or "").strip().lower()
    if status in {"queued", "pending", "processing", "running"}:
        return None
    if status not in {"completed", "failed"}:
        raise OpenShortsHostedTransportError("OpenShorts returned an unknown job status")
    canonical = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return evidence_store.record(OpenShortsTerminalEvidence(
        idempotency_key=idempotency_key,
        provider_job_id=record.external_reference,
        terminal_state=status.upper(),
        evidence_sha256=hashlib.sha256(canonical).hexdigest(),
        source="status_api",
    ))
