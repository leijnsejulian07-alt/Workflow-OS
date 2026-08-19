from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class RecoveryResult:
    idempotency_key: str
    state: str
    recovered: bool
    reason: str


def _parse_sqlite_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value or len(value) > 40:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return parsed


def recover_orphaned_execution(
    path: str | Path,
    idempotency_key: str,
    *,
    now: datetime,
    stale_after_seconds: int = 900,
) -> RecoveryResult:
    """Fail closed when an EXECUTING side effect may have outlived its process.

    This boundary never authorizes a retry. A stale or malformed EXECUTING record
    becomes UNKNOWN so provider-specific reconciliation must prove whether the
    external effect happened before any later retry can begin.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if not 1 <= stale_after_seconds <= 86_400:
        raise ValueError("stale_after_seconds must be between 1 and 86400")
    key = idempotency_key.strip() if isinstance(idempotency_key, str) else ""
    if not key or len(key) > 200:
        raise ValueError("idempotency_key must be 1..200 characters")

    db = sqlite3.connect(str(path), timeout=5.0)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA busy_timeout = 5000")
    try:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT idempotency_key, state, updated_at FROM side_effects WHERE idempotency_key=?",
            (key,),
        ).fetchone()
        if row is None:
            raise KeyError(key)
        state = str(row["state"])
        if state != "EXECUTING":
            db.commit()
            return RecoveryResult(key, state, False, "not-executing")

        freshness = _parse_sqlite_timestamp(row["updated_at"])
        now_utc = now.astimezone(timezone.utc)
        if freshness is not None:
            age_seconds = (now_utc - freshness).total_seconds()
            if 0 <= age_seconds < stale_after_seconds:
                db.commit()
                return RecoveryResult(key, "EXECUTING", False, "fresh")
            reason = "stale" if age_seconds >= stale_after_seconds else "invalid-future-freshness"
        else:
            reason = "malformed-freshness"

        # UNKNOWN is deliberately non-retryable. Existing reconciliation must
        # prove applied/not-applied before the state machine can progress.
        db.execute(
            "UPDATE side_effects SET state='UNKNOWN', updated_at=CURRENT_TIMESTAMP "
            "WHERE idempotency_key=? AND state='EXECUTING'",
            (key,),
        )
        changed = db.execute("SELECT changes()").fetchone()[0]
        final = db.execute(
            "SELECT state FROM side_effects WHERE idempotency_key=?", (key,)
        ).fetchone()
        db.commit()
        final_state = str(final["state"])
        return RecoveryResult(key, final_state, bool(changed), reason)
    finally:
        db.close()
