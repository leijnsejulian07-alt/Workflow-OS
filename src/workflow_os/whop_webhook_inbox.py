from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .adapters.whop_webhook import VerifiedWhopWebhook
from .sqlite_lifecycle import managed_connection

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_EVENT_JSON_BYTES = 256 * 1024


@dataclass(frozen=True)
class WhopInboxEvent:
    webhook_id: str
    event_type: str
    occurred_at: str
    account_id: str | None
    payload_sha256: str
    data: dict[str, object]
    status: str


def _utc(value: datetime | None = None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return current.astimezone(timezone.utc).isoformat()


def _canonical_data(data: object) -> str:
    if not isinstance(data, dict):
        raise ValueError("verified webhook data must be an object")
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if len(encoded.encode("utf-8")) > _MAX_EVENT_JSON_BYTES:
        raise ValueError("verified webhook data exceeds inbox limit")
    return encoded


class WhopWebhookInbox:
    """Durable idempotent inbox for already-verified Whop webhooks.

    Signature validation belongs to ``verify_whop_webhook``. This ledger only accepts
    its typed output, persists no secrets, and prevents at-least-once webhook delivery
    from silently creating multiple logical events. Event-specific revenue handlers
    must remain independently idempotent and fail closed.
    """

    def __init__(self, path: str | Path):
        self.path = str(path)
        with managed_connection(self._connect()) as db:
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS whop_webhook_inbox (
                    webhook_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    account_id TEXT,
                    payload_sha256 TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('PENDING','PROCESSED')),
                    received_at TEXT NOT NULL,
                    processed_at TEXT
                )
                """
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_whop_webhook_inbox_status ON whop_webhook_inbox(status, received_at)"
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout = 5000")
        return db

    def record(self, event: VerifiedWhopWebhook, *, received_at: datetime | None = None) -> WhopInboxEvent:
        if not isinstance(event, VerifiedWhopWebhook):
            raise TypeError("event must be VerifiedWhopWebhook")
        if not _SHA256_RE.fullmatch(event.payload_sha256):
            raise ValueError("verified webhook payload digest is invalid")
        data_json = _canonical_data(dict(event.data))
        received = _utc(received_at)
        identity = (
            event.event_type,
            event.occurred_at,
            event.account_id,
            event.payload_sha256,
            data_json,
        )
        with managed_connection(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                """SELECT event_type, occurred_at, account_id, payload_sha256, data_json, status
                   FROM whop_webhook_inbox WHERE webhook_id=?""",
                (event.webhook_id,),
            ).fetchone()
            if existing is not None:
                existing_identity = (
                    existing["event_type"],
                    existing["occurred_at"],
                    existing["account_id"],
                    existing["payload_sha256"],
                    existing["data_json"],
                )
                if existing_identity != identity:
                    raise ValueError("webhook_id already exists with different verified content")
                status = str(existing["status"])
            else:
                db.execute(
                    """INSERT INTO whop_webhook_inbox(
                           webhook_id,event_type,occurred_at,account_id,payload_sha256,
                           data_json,status,received_at,processed_at
                       ) VALUES(?,?,?,?,?,?,'PENDING',?,NULL)""",
                    (
                        event.webhook_id,
                        event.event_type,
                        event.occurred_at,
                        event.account_id,
                        event.payload_sha256,
                        data_json,
                        received,
                    ),
                )
                status = "PENDING"
        return WhopInboxEvent(
            webhook_id=event.webhook_id,
            event_type=event.event_type,
            occurred_at=event.occurred_at,
            account_id=event.account_id,
            payload_sha256=event.payload_sha256,
            data=json.loads(data_json),
            status=status,
        )

    def pending(self, *, limit: int = 50) -> list[WhopInboxEvent]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError("limit must be an integer between 1 and 200")
        with managed_connection(self._connect()) as db:
            rows = db.execute(
                """SELECT webhook_id,event_type,occurred_at,account_id,payload_sha256,data_json,status
                   FROM whop_webhook_inbox WHERE status='PENDING'
                   ORDER BY received_at, webhook_id LIMIT ?""",
                (limit,),
            ).fetchall()
        return [
            WhopInboxEvent(
                webhook_id=str(row["webhook_id"]),
                event_type=str(row["event_type"]),
                occurred_at=str(row["occurred_at"]),
                account_id=row["account_id"],
                payload_sha256=str(row["payload_sha256"]),
                data=json.loads(str(row["data_json"])),
                status=str(row["status"]),
            )
            for row in rows
        ]

    def mark_processed(
        self,
        webhook_id: str,
        *,
        expected_payload_sha256: str,
        processed_at: datetime | None = None,
    ) -> None:
        webhook_id = webhook_id.strip()
        if not webhook_id:
            raise ValueError("webhook_id is required")
        if not _SHA256_RE.fullmatch(expected_payload_sha256):
            raise ValueError("expected_payload_sha256 is invalid")
        processed = _utc(processed_at)
        with managed_connection(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT payload_sha256,status FROM whop_webhook_inbox WHERE webhook_id=?",
                (webhook_id,),
            ).fetchone()
            if row is None:
                raise ValueError("webhook event does not exist")
            if str(row["payload_sha256"]) != expected_payload_sha256:
                raise ValueError("webhook payload digest drifted before acknowledgement")
            if row["status"] == "PROCESSED":
                return
            db.execute(
                "UPDATE whop_webhook_inbox SET status='PROCESSED', processed_at=? WHERE webhook_id=?",
                (processed, webhook_id),
            )
