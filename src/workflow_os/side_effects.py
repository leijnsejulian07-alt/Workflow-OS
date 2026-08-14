from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_ALLOWED_STATES = {"RESERVED", "EXECUTING", "SUCCEEDED", "FAILED_RETRYABLE", "UNKNOWN"}
_MAX_PAYLOAD_BYTES = 64 * 1024


def _canonical_json(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if len(encoded.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
        raise ValueError("side-effect payload exceeds 64 KiB")
    return encoded


def _fingerprint(action: str, target: str, payload_json: str) -> str:
    raw = f"{action}\n{target}\n{payload_json}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class SideEffectRecord:
    idempotency_key: str
    action: str
    target: str
    request_fingerprint: str
    state: str
    attempt_count: int
    max_attempts: int
    external_reference: str | None


class SideEffectLedger:
    """Fail-closed idempotency and reconciliation boundary for external effects.

    A key is permanently bound to one canonical action/target/payload fingerprint.
    Ambiguous execution outcomes become UNKNOWN and cannot be retried until a
    caller explicitly reconciles whether the external effect happened.
    """

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout = 5000")
        return db

    def _init_schema(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS side_effects (
                    idempotency_key TEXT PRIMARY KEY,
                    action TEXT NOT NULL,
                    target TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    request_fingerprint TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('RESERVED','EXECUTING','SUCCEEDED','FAILED_RETRYABLE','UNKNOWN')),
                    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
                    max_attempts INTEGER NOT NULL CHECK(max_attempts BETWEEN 1 AND 10),
                    external_reference TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def reserve(
        self,
        *,
        idempotency_key: str,
        action: str,
        target: str,
        payload: Any,
        max_attempts: int = 3,
    ) -> SideEffectRecord:
        key = idempotency_key.strip()
        action = action.strip()
        target = target.strip()
        if not key or len(key) > 200:
            raise ValueError("idempotency_key must be 1..200 characters")
        if not action or len(action) > 100:
            raise ValueError("action must be 1..100 characters")
        if not target or len(target) > 500:
            raise ValueError("target must be 1..500 characters")
        if not 1 <= max_attempts <= 10:
            raise ValueError("max_attempts must be between 1 and 10")

        request_json = _canonical_json(payload)
        fingerprint = _fingerprint(action, target, request_json)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM side_effects WHERE idempotency_key = ?", (key,)
            ).fetchone()
            if row:
                if row["request_fingerprint"] != fingerprint:
                    raise ValueError("idempotency key is already bound to a different side effect")
                return self._row(row)
            db.execute(
                """
                INSERT INTO side_effects(
                    idempotency_key, action, target, request_json,
                    request_fingerprint, state, max_attempts
                ) VALUES(?, ?, ?, ?, ?, 'RESERVED', ?)
                """,
                (key, action, target, request_json, fingerprint, max_attempts),
            )
            row = db.execute(
                "SELECT * FROM side_effects WHERE idempotency_key = ?", (key,)
            ).fetchone()
            return self._row(row)

    def begin_attempt(self, idempotency_key: str) -> SideEffectRecord:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._require(db, idempotency_key)
            if row["state"] not in {"RESERVED", "FAILED_RETRYABLE"}:
                raise RuntimeError(f"side effect is not retry-authorized from state {row['state']}")
            if row["attempt_count"] >= row["max_attempts"]:
                raise RuntimeError("side effect retry budget exhausted")
            db.execute(
                """
                UPDATE side_effects
                SET state='EXECUTING', attempt_count=attempt_count+1, updated_at=CURRENT_TIMESTAMP
                WHERE idempotency_key=?
                """,
                (idempotency_key,),
            )
            return self._row(self._require(db, idempotency_key))

    def mark_succeeded(self, idempotency_key: str, *, external_reference: str | None = None) -> SideEffectRecord:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._require(db, idempotency_key)
            if row["state"] == "SUCCEEDED":
                if external_reference and row["external_reference"] not in {None, external_reference}:
                    raise ValueError("conflicting external reference for completed side effect")
                return self._row(row)
            if row["state"] not in {"EXECUTING", "UNKNOWN"}:
                raise RuntimeError("success can only follow execution or reconciliation of UNKNOWN")
            db.execute(
                "UPDATE side_effects SET state='SUCCEEDED', external_reference=?, updated_at=CURRENT_TIMESTAMP WHERE idempotency_key=?",
                (external_reference, idempotency_key),
            )
            return self._row(self._require(db, idempotency_key))

    def mark_failed(self, idempotency_key: str, *, definitely_not_applied: bool) -> SideEffectRecord:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._require(db, idempotency_key)
            if row["state"] != "EXECUTING":
                raise RuntimeError("failure can only follow EXECUTING")
            state = "FAILED_RETRYABLE" if definitely_not_applied else "UNKNOWN"
            db.execute(
                "UPDATE side_effects SET state=?, updated_at=CURRENT_TIMESTAMP WHERE idempotency_key=?",
                (state, idempotency_key),
            )
            return self._row(self._require(db, idempotency_key))

    def reconcile_not_applied(self, idempotency_key: str) -> SideEffectRecord:
        """Authorize a retry only after external reconciliation proves no effect occurred."""
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._require(db, idempotency_key)
            if row["state"] != "UNKNOWN":
                raise RuntimeError("only UNKNOWN side effects require not-applied reconciliation")
            db.execute(
                "UPDATE side_effects SET state='FAILED_RETRYABLE', updated_at=CURRENT_TIMESTAMP WHERE idempotency_key=?",
                (idempotency_key,),
            )
            return self._row(self._require(db, idempotency_key))

    def get(self, idempotency_key: str) -> SideEffectRecord | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM side_effects WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        return self._row(row) if row else None

    @staticmethod
    def _require(db: sqlite3.Connection, idempotency_key: str) -> sqlite3.Row:
        row = db.execute("SELECT * FROM side_effects WHERE idempotency_key=?", (idempotency_key,)).fetchone()
        if not row:
            raise KeyError(idempotency_key)
        return row

    @staticmethod
    def _row(row: sqlite3.Row) -> SideEffectRecord:
        state = str(row["state"])
        if state not in _ALLOWED_STATES:
            raise RuntimeError("invalid persisted side-effect state")
        return SideEffectRecord(
            idempotency_key=str(row["idempotency_key"]),
            action=str(row["action"]),
            target=str(row["target"]),
            request_fingerprint=str(row["request_fingerprint"]),
            state=state,
            attempt_count=int(row["attempt_count"]),
            max_attempts=int(row["max_attempts"]),
            external_reference=row["external_reference"],
        )
