from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .adapters.openshorts_hosted import OpenShortsHostedTransport
from .openshorts_execution import OpenShortsExecutionEvidenceStore, observe_terminal_status
from .openshorts_output_provenance import (
    OpenShortsOutputProvenanceStore,
    record_completed_status_clip_outputs,
)
from .openshorts_runtime_entrypoint import load_openshorts_runtime_config
from .openshorts_whop_enqueue import enqueue_completed_openshorts_whop_jobs
from .side_effects import SideEffectLedger
from .sqlite_lifecycle import managed_connection


@dataclass(frozen=True)
class OpenShortsTerminalReconciliationCycleResult:
    checked: int
    terminal: int
    pending: int
    outputs_recorded: int = 0
    submission_jobs_enqueued: int = 0


def _candidate_idempotency_keys(path: str | Path, *, limit: int) -> tuple[str, ...]:
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise TypeError("limit must be an integer")
    if not 1 <= limit <= 4:
        raise ValueError("limit must be between 1 and 4")

    db_path = str(path)
    SideEffectLedger(db_path)
    OpenShortsExecutionEvidenceStore(db_path)
    with managed_connection(sqlite3.connect(db_path, timeout=5.0)) as db:
        rows = db.execute(
            """
            SELECT s.idempotency_key
            FROM side_effects AS s
            LEFT JOIN openshorts_terminal_evidence AS e
              ON e.idempotency_key = s.idempotency_key
            WHERE s.action = 'openshorts.process'
              AND s.state = 'SUCCEEDED'
              AND s.external_reference IS NOT NULL
              AND e.idempotency_key IS NULL
            ORDER BY s.updated_at ASC, s.idempotency_key ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return tuple(str(row[0]) for row in rows)


def run_bounded_openshorts_terminal_reconciliation(
    *,
    state_db_path: str | Path,
    api_key: str,
    max_checks: int = 1,
    transport: OpenShortsHostedTransport | None = None,
    available_at: object | None = None,
) -> OpenShortsTerminalReconciliationCycleResult:
    """Poll at most four confirmed jobs and persist terminal/output evidence.

    Completed status payloads are converted to immutable clip provenance and,
    for canonical durable render keys, separate `submit_reward` jobs before
    terminal evidence is committed. This ordering keeps crashes replayable: both
    provenance recording and queue enqueue are idempotent, so the next bounded
    cycle can safely repeat them before sealing terminal evidence.
    """
    runtime_transport = transport or OpenShortsHostedTransport()
    db_path = str(state_db_path)
    ledger = SideEffectLedger(db_path)
    evidence_store = OpenShortsExecutionEvidenceStore(db_path)
    output_store = OpenShortsOutputProvenanceStore(db_path)
    keys = _candidate_idempotency_keys(db_path, limit=max_checks)
    child_available_at = available_at or datetime.now(timezone.utc).isoformat()

    terminal = 0
    pending = 0
    outputs_recorded = 0
    submission_jobs_enqueued = 0
    for key in keys:
        observation = observe_terminal_status(
            ledger=ledger,
            idempotency_key=key,
            transport=runtime_transport,
            api_key=api_key,
        )
        if observation is None:
            pending += 1
            continue
        if observation.evidence.terminal_state == "COMPLETED":
            outputs = record_completed_status_clip_outputs(
                ledger=ledger,
                store=output_store,
                terminal_evidence=observation.evidence,
                status_payload=observation.payload,
            )
            outputs_recorded += len(outputs)
            if key.startswith("openshorts:"):
                child_jobs = enqueue_completed_openshorts_whop_jobs(
                    state_db_path=db_path,
                    openshorts_idempotency_key=key,
                    outputs=outputs,
                    available_at=child_available_at,
                )
                submission_jobs_enqueued += len(child_jobs)
        evidence_store.record(observation.evidence)
        terminal += 1

    return OpenShortsTerminalReconciliationCycleResult(
        checked=len(keys),
        terminal=terminal,
        pending=pending,
        outputs_recorded=outputs_recorded,
        submission_jobs_enqueued=submission_jobs_enqueued,
    )


def main() -> int:
    config = load_openshorts_runtime_config()
    result = run_bounded_openshorts_terminal_reconciliation(
        state_db_path=config.state_db_path,
        api_key=config.api_key,
        max_checks=config.max_jobs,
    )
    print(json.dumps({
        "checked": result.checked,
        "terminal": result.terminal,
        "pending": result.pending,
        "outputs_recorded": result.outputs_recorded,
        "submission_jobs_enqueued": result.submission_jobs_enqueued,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
