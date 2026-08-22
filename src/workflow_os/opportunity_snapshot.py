from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from .ledger import OpportunityLedger


@dataclass(frozen=True)
class OpportunitySnapshot:
    opportunity_id: str
    payload: dict[str, Any]
    sha256: str


def snapshot_opportunity(ledger: OpportunityLedger, opportunity_id: object) -> OpportunitySnapshot:
    """Read one normalized opportunity as a digest-bound durable job snapshot."""
    if not isinstance(ledger, OpportunityLedger):
        raise TypeError("ledger must be OpportunityLedger")
    if not isinstance(opportunity_id, str):
        raise ValueError("opportunity_id must be a string")
    op_id = opportunity_id.strip()
    if not op_id or len(op_id) > 200 or any(ord(ch) < 32 for ch in op_id):
        raise ValueError("invalid opportunity_id")

    with sqlite3.connect(ledger.path, timeout=5.0) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=5000")
        row = db.execute(
            "SELECT normalized_json FROM opportunities WHERE opportunity_id=?",
            (op_id,),
        ).fetchone()

    if row is None:
        raise KeyError(op_id)
    try:
        payload = json.loads(row["normalized_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("persisted normalized opportunity is invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("persisted normalized opportunity must be an object")
    if payload.get("opportunity_id") != op_id:
        raise RuntimeError("persisted normalized opportunity identity mismatch")

    try:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RuntimeError("persisted normalized opportunity is not canonicalizable") from exc
    return OpportunitySnapshot(
        opportunity_id=op_id,
        payload=payload,
        sha256=hashlib.sha256(canonical).hexdigest(),
    )


def verify_opportunity_snapshot(payload: object, sha256: object, opportunity_id: object) -> dict[str, Any]:
    """Verify a queued snapshot before a restarted worker trusts it."""
    if not isinstance(payload, dict):
        raise ValueError("opportunity snapshot must be an object")
    if not isinstance(sha256, str) or len(sha256) != 64 or sha256.lower() != sha256:
        raise ValueError("opportunity snapshot digest must be lowercase SHA-256")
    if not isinstance(opportunity_id, str) or payload.get("opportunity_id") != opportunity_id:
        raise ValueError("opportunity snapshot identity mismatch")
    try:
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("opportunity snapshot is not canonicalizable") from exc
    expected = hashlib.sha256(canonical).hexdigest()
    if expected != sha256:
        raise ValueError("opportunity snapshot digest mismatch")
    return json.loads(canonical.decode("utf-8"))
