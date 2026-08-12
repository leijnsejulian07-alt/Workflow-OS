from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS opportunities (
  opportunity_id TEXT PRIMARY KEY,
  source_platform TEXT NOT NULL,
  campaign_id TEXT,
  title TEXT NOT NULL,
  category TEXT NOT NULL,
  raw_json TEXT NOT NULL,
  normalized_json TEXT NOT NULL,
  status TEXT NOT NULL,
  rejection_reason TEXT,
  expected_collectible_revenue REAL NOT NULL DEFAULT 0,
  expected_production_cost REAL NOT NULL DEFAULT 0,
  expected_net_profit REAL NOT NULL DEFAULT 0,
  expected_laptop_minutes REAL NOT NULL DEFAULT 0,
  expected_profit_per_laptop_hour REAL NOT NULL DEFAULT 0,
  rights_verification_state TEXT NOT NULL DEFAULT 'UNKNOWN',
  compliance_risk TEXT NOT NULL DEFAULT 'MEDIUM',
  platform_risk TEXT NOT NULL DEFAULT 'MEDIUM',
  user_attention_requirement TEXT NOT NULL DEFAULT 'NONE',
  source_checked_at TEXT NOT NULL,
  freshness_ttl_seconds INTEGER NOT NULL DEFAULT 3600,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  event_type TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS side_effects (
  side_effect_key TEXT PRIMARY KEY,
  opportunity_id TEXT NOT NULL,
  effect_type TEXT NOT NULL,
  state TEXT NOT NULL,
  external_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS revenue_events (
  revenue_event_id TEXT PRIMARY KEY,
  opportunity_id TEXT NOT NULL,
  state TEXT NOT NULL,
  gross_amount REAL NOT NULL,
  fees REAL NOT NULL DEFAULT 0,
  currency TEXT NOT NULL,
  amount_eur REAL,
  external_id TEXT,
  evidence_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""


def init_db(path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)


@contextmanager
def connect(path: str | Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def audit(conn: sqlite3.Connection, ts: str, event_type: str, entity_type: str, entity_id: str, payload: dict) -> None:
    conn.execute(
        "INSERT INTO audit_log(ts,event_type,entity_type,entity_id,payload_json) VALUES (?,?,?,?,?)",
        (ts, event_type, entity_type, entity_id, json.dumps(payload, sort_keys=True)),
    )
