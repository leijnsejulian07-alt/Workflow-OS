from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .sqlite_lifecycle import managed_connection

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ExperimentReservation:
    opportunity_id: str
    experiment_key: str
    reserved_at: str
    status: str


class ExperimentLedger:
    """Persistent first-experiment budget for zero-sample opportunities."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout = 5000")
        return db

    def _init_schema(self) -> None:
        with managed_connection(self._connect()) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS experiment_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS experiment_reservations (
                    opportunity_id TEXT PRIMARY KEY,
                    experiment_key TEXT NOT NULL UNIQUE,
                    reserved_at TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('RESERVED','CONSUMED'))
                );
                """
            )
            db.execute(
                "INSERT INTO experiment_meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),),
            )

    @staticmethod
    def _identifier(value: object, name: str, *, max_len: int = 200) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{name} must be a string")
        cleaned = value.strip()
        if not cleaned or len(cleaned) > max_len or any(ord(ch) < 32 for ch in cleaned):
            raise ValueError(f"invalid {name}")
        return cleaned

    @staticmethod
    def _timestamp(value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("reserved_at must be an ISO-8601 timestamp")
        text = value.strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("reserved_at must be an ISO-8601 timestamp") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("reserved_at must include a timezone offset")
        return parsed.isoformat()

    def reserve_first_experiment(
        self,
        *,
        opportunity_id: object,
        experiment_key: object,
        reserved_at: object,
    ) -> ExperimentReservation:
        opportunity = self._identifier(opportunity_id, "opportunity_id")
        key = self._identifier(experiment_key, "experiment_key")
        timestamp = self._timestamp(reserved_at)

        with managed_connection(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM experiment_reservations WHERE opportunity_id=?",
                (opportunity,),
            ).fetchone()
            if existing is not None:
                if existing["experiment_key"] == key and existing["reserved_at"] == timestamp:
                    return self._row(existing)
                raise ValueError("opportunity already has a first-experiment reservation")

            key_owner = db.execute(
                "SELECT opportunity_id FROM experiment_reservations WHERE experiment_key=?",
                (key,),
            ).fetchone()
            if key_owner is not None:
                raise ValueError("experiment_key already belongs to another opportunity")

            db.execute(
                "INSERT INTO experiment_reservations(opportunity_id, experiment_key, reserved_at, status) "
                "VALUES(?, ?, ?, 'RESERVED')",
                (opportunity, key, timestamp),
            )

        return ExperimentReservation(opportunity, key, timestamp, "RESERVED")

    def mark_consumed(self, opportunity_id: object) -> ExperimentReservation:
        opportunity = self._identifier(opportunity_id, "opportunity_id")
        with managed_connection(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM experiment_reservations WHERE opportunity_id=?",
                (opportunity,),
            ).fetchone()
            if row is None:
                raise ValueError("experiment reservation does not exist")
            if row["status"] != "CONSUMED":
                db.execute(
                    "UPDATE experiment_reservations SET status='CONSUMED' WHERE opportunity_id=?",
                    (opportunity,),
                )
                row = db.execute(
                    "SELECT * FROM experiment_reservations WHERE opportunity_id=?",
                    (opportunity,),
                ).fetchone()
            return self._row(row)

    def get(self, opportunity_id: object) -> ExperimentReservation | None:
        opportunity = self._identifier(opportunity_id, "opportunity_id")
        with managed_connection(self._connect()) as db:
            row = db.execute(
                "SELECT * FROM experiment_reservations WHERE opportunity_id=?",
                (opportunity,),
            ).fetchone()
        return None if row is None else self._row(row)

    def may_reserve_first_experiment(self, opportunity_id: object) -> bool:
        return self.get(opportunity_id) is None

    @staticmethod
    def _row(row: sqlite3.Row) -> ExperimentReservation:
        return ExperimentReservation(
            opportunity_id=row["opportunity_id"],
            experiment_key=row["experiment_key"],
            reserved_at=row["reserved_at"],
            status=row["status"],
        )
