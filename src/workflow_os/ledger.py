from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .opportunities import OpportunityDecision

SCHEMA_VERSION = 1


class OpportunityLedger:
    """Small local-first SQLite ledger for normalized opportunities and decisions.

    The ledger stores decision snapshots rather than inventing cash state. Revenue
    reconciliation remains a separate ledger. SQLite is an implementation detail
    behind this class so a future cloud store can replace it without changing the
    Opportunity Manager contract.
    """

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _init_schema(self) -> None:
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS workflow_os_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS opportunities (
                    opportunity_id TEXT PRIMARY KEY,
                    normalized_json TEXT NOT NULL,
                    source_platform TEXT NOT NULL,
                    campaign_id TEXT,
                    discovered_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS opportunity_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    opportunity_id TEXT NOT NULL,
                    evaluated_at TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    decision TEXT NOT NULL CHECK(decision IN ('ACCEPT','REVALIDATE','PAUSE','REJECT')),
                    eligible_for_queue INTEGER NOT NULL CHECK(eligible_for_queue IN (0,1)),
                    priority_score REAL NOT NULL,
                    decision_json TEXT NOT NULL,
                    UNIQUE(opportunity_id, evaluated_at, policy_version),
                    FOREIGN KEY(opportunity_id) REFERENCES opportunities(opportunity_id)
                );
                CREATE INDEX IF NOT EXISTS idx_opportunity_decisions_latest
                    ON opportunity_decisions(opportunity_id, evaluated_at DESC);
                """
            )
            db.execute(
                "INSERT INTO workflow_os_meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),),
            )

    def record(self, opportunity: dict[str, Any], decision: OpportunityDecision) -> None:
        opportunity_id = str(opportunity.get("opportunity_id") or "")
        if not opportunity_id or opportunity_id != decision.opportunity_id:
            raise ValueError("opportunity and decision IDs must match")
        discovered_at = str(opportunity.get("discovered_at") or "")
        if not discovered_at:
            raise ValueError("normalized opportunity must include discovered_at")

        normalized_json = json.dumps(opportunity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        decision_dict = decision.to_dict()
        decision_json = json.dumps(decision_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """
                INSERT INTO opportunities(opportunity_id, normalized_json, source_platform, campaign_id, discovered_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(opportunity_id) DO UPDATE SET
                    normalized_json=excluded.normalized_json,
                    source_platform=excluded.source_platform,
                    campaign_id=excluded.campaign_id,
                    updated_at=excluded.updated_at
                """,
                (
                    opportunity_id,
                    normalized_json,
                    str(opportunity.get("source_platform") or "unknown"),
                    opportunity.get("campaign_id"),
                    discovered_at,
                    decision.evaluated_at,
                ),
            )
            db.execute(
                """
                INSERT INTO opportunity_decisions(
                    opportunity_id, evaluated_at, policy_version, decision,
                    eligible_for_queue, priority_score, decision_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(opportunity_id, evaluated_at, policy_version) DO UPDATE SET
                    decision=excluded.decision,
                    eligible_for_queue=excluded.eligible_for_queue,
                    priority_score=excluded.priority_score,
                    decision_json=excluded.decision_json
                """,
                (
                    opportunity_id,
                    decision.evaluated_at,
                    decision.policy_version,
                    decision.decision,
                    int(decision.eligible_for_queue),
                    decision.priority_score,
                    decision_json,
                ),
            )

    def latest_decision(self, opportunity_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT decision_json FROM opportunity_decisions
                WHERE opportunity_id = ?
                ORDER BY evaluated_at DESC, id DESC LIMIT 1
                """,
                (opportunity_id,),
            ).fetchone()
        return json.loads(row["decision_json"]) if row else None

    def queue_candidates(self, limit: int = 50) -> list[dict[str, Any]]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        with self._connect() as db:
            rows = db.execute(
                """
                WITH latest AS (
                    SELECT opportunity_id, MAX(id) AS decision_id
                    FROM opportunity_decisions GROUP BY opportunity_id
                )
                SELECT d.decision_json
                FROM latest l JOIN opportunity_decisions d ON d.id = l.decision_id
                WHERE d.decision = 'ACCEPT' AND d.eligible_for_queue = 1
                ORDER BY d.priority_score DESC, d.id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [json.loads(row["decision_json"]) for row in rows]
