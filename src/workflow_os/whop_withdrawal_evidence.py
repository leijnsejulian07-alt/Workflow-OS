from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .whop_webhook_inbox import WhopInboxEvent

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9_:-]{1,300}$")
_MAX_AMOUNT = Decimal("1000000")
_ALLOWED_EVENT_TYPES = {"withdrawal.created", "withdrawal.updated"}


@dataclass(frozen=True)
class WhopWithdrawalEvidence:
    webhook_id: str
    withdrawal_id: str
    event_type: str
    occurred_at: str
    account_id: str | None
    amount: str
    currency: str | None
    status: str | None
    trace_code: str | None
    payload_sha256: str

    @property
    def proves_received_cash(self) -> bool:
        return False


def _bounded_id(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    cleaned = value.strip()
    if not _ID_RE.fullmatch(cleaned):
        raise ValueError(f"{name} is invalid")
    return cleaned


def _optional_text(value: object, name: str, *, max_len: int = 200) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string when present")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > max_len or any(ord(ch) < 32 for ch in cleaned):
        raise ValueError(f"{name} is invalid")
    return cleaned


def _amount(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError("withdrawal amount is invalid")
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("withdrawal amount is invalid") from exc
    if not amount.is_finite() or amount <= 0 or amount >= _MAX_AMOUNT:
        raise ValueError("withdrawal amount is outside allowed bounds")
    return format(amount.normalize(), "f")


def _occurred_at(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("withdrawal event timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("withdrawal event timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc).isoformat()


def normalize_whop_withdrawal_event(event: WhopInboxEvent) -> WhopWithdrawalEvidence:
    """Normalize a verified, durably-inboxed Whop withdrawal event.

    A withdrawal event is payout-status evidence only. It never proves that money
    reached the external bank/wallet, so this module intentionally has no CashReceipt
    conversion and cannot feed realized-cash scaling truth by itself.
    """
    if not isinstance(event, WhopInboxEvent):
        raise TypeError("event must be WhopInboxEvent")
    if event.event_type not in _ALLOWED_EVENT_TYPES:
        raise ValueError("event is not a supported Whop withdrawal webhook")
    if not _SHA256_RE.fullmatch(event.payload_sha256):
        raise ValueError("payload digest is invalid")
    if not isinstance(event.data, dict):
        raise ValueError("withdrawal webhook data must be an object")

    withdrawal_id = _bounded_id(event.data.get("id"), "withdrawal_id")
    account_id = _optional_text(event.account_id, "account_id", max_len=300)

    ledger_account = event.data.get("ledger_account")
    if ledger_account is not None:
        if not isinstance(ledger_account, dict):
            raise ValueError("ledger_account must be an object when present")
        nested_company_id = _optional_text(
            ledger_account.get("company_id"), "ledger_account.company_id", max_len=300
        )
        if account_id is not None and nested_company_id is not None and account_id != nested_company_id:
            raise ValueError("withdrawal company identity does not match webhook account")

    currency = _optional_text(event.data.get("currency"), "currency", max_len=16)
    if currency is not None:
        currency = currency.upper()
    status = _optional_text(event.data.get("status"), "status", max_len=80)
    trace_code = _optional_text(event.data.get("trace_code"), "trace_code", max_len=200)

    return WhopWithdrawalEvidence(
        webhook_id=_bounded_id(event.webhook_id, "webhook_id"),
        withdrawal_id=withdrawal_id,
        event_type=event.event_type,
        occurred_at=_occurred_at(event.occurred_at),
        account_id=account_id,
        amount=_amount(event.data.get("amount")),
        currency=currency,
        status=status,
        trace_code=trace_code,
        payload_sha256=event.payload_sha256,
    )


class WhopWithdrawalEvidenceLedger:
    """Append-only semantic evidence for Whop withdrawal webhooks.

    This is deliberately separate from RevenueReconciliationLedger. It persists
    payout/withdrawal evidence until independent external receipt reconciliation is
    available, without ever asserting received cash.
    """

    def __init__(self, path: str | Path):
        self.path = str(path)
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS whop_withdrawal_evidence (
                    webhook_id TEXT PRIMARY KEY,
                    withdrawal_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    account_id TEXT,
                    amount TEXT NOT NULL,
                    currency TEXT,
                    status TEXT,
                    trace_code TEXT,
                    payload_sha256 TEXT NOT NULL,
                    evidence_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_whop_withdrawal_id
                    ON whop_withdrawal_evidence(withdrawal_id, occurred_at);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout = 5000")
        return db

    def record(self, evidence: WhopWithdrawalEvidence) -> None:
        if not isinstance(evidence, WhopWithdrawalEvidence):
            raise TypeError("evidence must be WhopWithdrawalEvidence")
        payload = json.dumps(
            {
                "webhook_id": evidence.webhook_id,
                "withdrawal_id": evidence.withdrawal_id,
                "event_type": evidence.event_type,
                "occurred_at": evidence.occurred_at,
                "account_id": evidence.account_id,
                "amount": evidence.amount,
                "currency": evidence.currency,
                "status": evidence.status,
                "trace_code": evidence.trace_code,
                "payload_sha256": evidence.payload_sha256,
                "proves_received_cash": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT evidence_json FROM whop_withdrawal_evidence WHERE webhook_id=?",
                (evidence.webhook_id,),
            ).fetchone()
            if existing is not None:
                if str(existing["evidence_json"]) != payload:
                    raise ValueError("webhook_id already exists with different withdrawal evidence")
                return
            db.execute(
                """INSERT INTO whop_withdrawal_evidence(
                       webhook_id,withdrawal_id,event_type,occurred_at,account_id,amount,
                       currency,status,trace_code,payload_sha256,evidence_json
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    evidence.webhook_id,
                    evidence.withdrawal_id,
                    evidence.event_type,
                    evidence.occurred_at,
                    evidence.account_id,
                    evidence.amount,
                    evidence.currency,
                    evidence.status,
                    evidence.trace_code,
                    evidence.payload_sha256,
                    payload,
                ),
            )

    def events_for_withdrawal(self, withdrawal_id: str) -> list[WhopWithdrawalEvidence]:
        withdrawal_id = _bounded_id(withdrawal_id, "withdrawal_id")
        with self._connect() as db:
            rows = db.execute(
                """SELECT webhook_id,withdrawal_id,event_type,occurred_at,account_id,amount,
                          currency,status,trace_code,payload_sha256
                   FROM whop_withdrawal_evidence
                   WHERE withdrawal_id=?
                   ORDER BY occurred_at, webhook_id""",
                (withdrawal_id,),
            ).fetchall()
        return [
            WhopWithdrawalEvidence(
                webhook_id=str(row["webhook_id"]),
                withdrawal_id=str(row["withdrawal_id"]),
                event_type=str(row["event_type"]),
                occurred_at=str(row["occurred_at"]),
                account_id=row["account_id"],
                amount=str(row["amount"]),
                currency=row["currency"],
                status=row["status"],
                trace_code=row["trace_code"],
                payload_sha256=str(row["payload_sha256"]),
            )
            for row in rows
        ]
