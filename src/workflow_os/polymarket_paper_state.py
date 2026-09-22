from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .polymarket_paper import PolymarketPaperDecision


@dataclass(frozen=True)
class PaperAccount:
    bankroll_usd: float
    peak_bankroll_usd: float
    realized_pnl_usd: float
    stopped: bool
    stop_reason: str | None


@dataclass(frozen=True)
class PaperPosition:
    market_id: str
    stake_usd: float
    entry_price: float
    entry_fair_probability: float
    opened_at: datetime


class PolymarketPaperStore:
    """Small durable paper ledger. It never holds credentials or reaches live execution."""

    def __init__(self, path: str | Path, *, starting_bankroll_usd: float = 50.0):
        if (not isinstance(starting_bankroll_usd, (int, float)) or isinstance(starting_bankroll_usd, bool)
                or not math.isfinite(float(starting_bankroll_usd)) or float(starting_bankroll_usd) <= 0):
            raise ValueError('starting_bankroll_usd must be a positive finite number')
        self.path = str(path)
        self.starting_bankroll_usd = float(starting_bankroll_usd)
        self._init()

    def _connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def _init(self):
        with self._connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS paper_account (
              singleton INTEGER PRIMARY KEY CHECK(singleton=1), bankroll_usd REAL NOT NULL,
              peak_bankroll_usd REAL NOT NULL, realized_pnl_usd REAL NOT NULL DEFAULT 0,
              stopped INTEGER NOT NULL DEFAULT 0, stop_reason TEXT
            );
            CREATE TABLE IF NOT EXISTS paper_positions (
              market_id TEXT PRIMARY KEY, side TEXT NOT NULL, stake_usd REAL NOT NULL,
              entry_price REAL NOT NULL, entry_fair_probability REAL NOT NULL,
              opened_at TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN'
            );
            CREATE TABLE IF NOT EXISTS paper_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT, occurred_at TEXT NOT NULL,
              market_id TEXT, event_type TEXT NOT NULL, payload_json TEXT NOT NULL
            );
            """)
            db.execute("INSERT OR IGNORE INTO paper_account(singleton,bankroll_usd,peak_bankroll_usd) VALUES(1,?,?)",
                       (self.starting_bankroll_usd, self.starting_bankroll_usd))

    @staticmethod
    def _validate_account_row(row: sqlite3.Row | None) -> None:
        if row is None:
            raise RuntimeError('paper account missing')
        numeric_values = (row['bankroll_usd'], row['peak_bankroll_usd'], row['realized_pnl_usd'])
        if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value))
               for value in numeric_values):
            raise RuntimeError('paper account contains non-finite ledger state')
        if row['bankroll_usd'] < 0 or row['peak_bankroll_usd'] <= 0 or row['bankroll_usd'] > row['peak_bankroll_usd']:
            raise RuntimeError('paper account contains impossible ledger state')
        if row['stopped'] not in (0, 1):
            raise RuntimeError('paper account contains invalid stop state')

    @staticmethod
    def _validate_open_position_row(row: sqlite3.Row) -> None:
        if row['side'] != 'YES' or row['status'] != 'OPEN':
            raise RuntimeError('paper position contains invalid state')
        numeric_values = (row['stake_usd'], row['entry_price'], row['entry_fair_probability'])
        if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value))
               for value in numeric_values):
            raise RuntimeError('paper position contains non-finite ledger state')
        if row['stake_usd'] <= 0 or not (0 < row['entry_price'] < 1) or not (0 < row['entry_fair_probability'] < 1):
            raise RuntimeError('paper position contains impossible ledger state')

    def account(self) -> PaperAccount:
        with self._connect() as db:
            row = db.execute("SELECT * FROM paper_account WHERE singleton=1").fetchone()
        self._validate_account_row(row)
        return PaperAccount(row['bankroll_usd'], row['peak_bankroll_usd'], row['realized_pnl_usd'], bool(row['stopped']), row['stop_reason'])

    def open_count(self) -> int:
        with self._connect() as db:
            return int(db.execute("SELECT COUNT(*) FROM paper_positions WHERE status='OPEN'").fetchone()[0])

    def open_positions(self) -> tuple[PaperPosition, ...]:
        """Return validated durable positions for the monitoring/exit loop."""
        with self._connect() as db:
            rows = db.execute("SELECT * FROM paper_positions WHERE status='OPEN' ORDER BY opened_at, market_id").fetchall()
        positions: list[PaperPosition] = []
        for row in rows:
            self._validate_open_position_row(row)
            try:
                opened_at = datetime.fromisoformat(row['opened_at'])
                if opened_at.tzinfo is None or opened_at.utcoffset() is None:
                    raise ValueError
                opened_at = opened_at.astimezone(timezone.utc)
            except (TypeError, ValueError, OverflowError) as exc:
                raise RuntimeError('paper position contains invalid opened_at') from exc
            positions.append(PaperPosition(
                market_id=row['market_id'],
                stake_usd=float(row['stake_usd']),
                entry_price=float(row['entry_price']),
                entry_fair_probability=float(row['entry_fair_probability']),
                opened_at=opened_at,
            ))
        return tuple(positions)

    def record_decision(self, market_id: str, decision: PolymarketPaperDecision) -> None:
        with self._connect() as db:
            self._insert_event(db, market_id, 'DECISION', asdict(decision))

    def open_yes(self, *, market_id: str, stake_usd: float, entry_price: float, entry_fair_probability: float, opened_at: datetime | None = None) -> None:
        if not isinstance(market_id, str) or not market_id or market_id != market_id.strip():
            raise ValueError('invalid market id')
        numeric_values = (stake_usd, entry_price, entry_fair_probability)
        if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)) for value in numeric_values):
            raise ValueError('paper position values must be finite numbers')
        if stake_usd <= 0 or not (0 < entry_price < 1) or not (0 < entry_fair_probability < 1):
            raise ValueError('invalid paper position')
        if opened_at is not None:
            if not isinstance(opened_at, datetime):
                raise ValueError('opened_at must be an aware datetime')
            try:
                offset = opened_at.utcoffset()
            except Exception as exc:
                raise ValueError('opened_at must be an aware datetime') from exc
            if opened_at.tzinfo is None or offset is None:
                raise ValueError('opened_at must be an aware datetime')
        at = (opened_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        try:
            with self._connect() as db:
                account = db.execute("SELECT * FROM paper_account WHERE singleton=1").fetchone()
                self._validate_account_row(account)
                if account['stopped']:
                    raise RuntimeError('paper account stopped')
                if stake_usd > account['bankroll_usd']:
                    raise ValueError('stake exceeds bankroll')
                db.execute("INSERT INTO paper_positions(market_id,side,stake_usd,entry_price,entry_fair_probability,opened_at) VALUES(?,?,?,?,?,?)",
                           (market_id, 'YES', stake_usd, entry_price, entry_fair_probability, at))
                db.execute("UPDATE paper_account SET bankroll_usd=bankroll_usd-? WHERE singleton=1", (stake_usd,))
                self._insert_event(db, market_id, 'OPEN', {'stake_usd': stake_usd, 'entry_price': entry_price, 'entry_fair_probability': entry_fair_probability})
        except sqlite3.IntegrityError as exc:
            raise ValueError('paper position already exists or violates ledger constraints') from exc

    def close_yes(self, *, market_id: str, exit_price: float) -> float:
        if not isinstance(market_id, str) or not market_id or market_id != market_id.strip():
            raise ValueError('invalid market id')
        if (not isinstance(exit_price, (int, float)) or isinstance(exit_price, bool)
                or not math.isfinite(float(exit_price)) or not 0 <= exit_price <= 1):
            raise ValueError('invalid exit price')
        with self._connect() as db:
            account = db.execute("SELECT * FROM paper_account WHERE singleton=1").fetchone()
            self._validate_account_row(account)
            row = db.execute("SELECT * FROM paper_positions WHERE market_id=? AND status='OPEN'", (market_id,)).fetchone()
            if row is None:
                raise KeyError(market_id)
            self._validate_open_position_row(row)
            proceeds = row['stake_usd'] * exit_price / row['entry_price']
            pnl = proceeds - row['stake_usd']
            if not math.isfinite(proceeds) or not math.isfinite(pnl):
                raise ValueError('paper settlement must remain finite')
            db.execute("UPDATE paper_positions SET status='CLOSED' WHERE market_id=?", (market_id,))
            db.execute("UPDATE paper_account SET bankroll_usd=bankroll_usd+?, realized_pnl_usd=realized_pnl_usd+? WHERE singleton=1", (proceeds, pnl))
            current = db.execute("SELECT bankroll_usd,peak_bankroll_usd FROM paper_account WHERE singleton=1").fetchone()
            if current['bankroll_usd'] > current['peak_bankroll_usd']:
                db.execute("UPDATE paper_account SET peak_bankroll_usd=? WHERE singleton=1", (current['bankroll_usd'],))
            self._insert_event(db, market_id, 'CLOSE', {'exit_price': exit_price, 'pnl_usd': pnl})
        return pnl

    def stop(self, reason: str) -> None:
        with self._connect() as db:
            account = db.execute("SELECT * FROM paper_account WHERE singleton=1").fetchone()
            self._validate_account_row(account)
            db.execute("UPDATE paper_account SET stopped=1, stop_reason=? WHERE singleton=1", (reason,))
            self._insert_event(db, None, 'STOP', {'reason': reason})

    @staticmethod
    def _insert_event(db: sqlite3.Connection, market_id: str | None, event_type: str, payload: dict) -> None:
        db.execute("INSERT INTO paper_events(occurred_at,market_id,event_type,payload_json) VALUES(?,?,?,?)",
                   (datetime.now(timezone.utc).isoformat(), market_id, event_type, json.dumps(payload, sort_keys=True)))
