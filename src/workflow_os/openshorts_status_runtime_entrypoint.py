from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .adapters.openshorts_hosted import OpenShortsHostedTransport
from .openshorts_execution import (
    OpenShortsExecutionEvidenceStore,
    reconcile_terminal_status,
)
from .openshorts_runtime_entrypoint import load_openshorts_runtime_config
from .side_effects import SideEffectLedger
from .sqlite_lifecycle import managed_connection


@dataclass(frozen=True)
class OpenShortsTerminalReconciliationCycleResult:
    checked: int
    terminal: int
    pending: int


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
) -> OpenShortsTerminalReconciliationCycleResult:
    """Poll at most four confirmed OpenShorts jobs and persist terminal evidence.

    Only already-SUCCEEDED OpenShorts dispatches without terminal evidence are read.
    A non-terminal provider status is left unchanged for a later scheduler cycle.
    Provider/protocol failures propagate so the host scheduler can retry on its next
    bounded invocation instead of converting an ambiguous response into success.
    """
    runtime_transport = transport or OpenShortsHostedTransport()
    db_path = str(state_db_path)
    ledger = SideEffectLedger(db_path)
    evidence_store = OpenShortsExecutionEvidenceStore(db_path)
    keys = _candidate_idempotency_keys(db_path, limit=max_checks)

    terminal = 0
    pending = 0
    for key in keys:
        evidence = reconcile_terminal_status(
            ledger=ledger,
            evidence_store=evidence_store,
            idempotency_key=key,
            transport=runtime_transport,
            api_key=api_key,
        )
        if evidence is None:
            pending += 1
        else:
            terminal += 1

    return OpenShortsTerminalReconciliationCycleResult(
        checked=len(keys),
        terminal=terminal,
        pending=pending,
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
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
