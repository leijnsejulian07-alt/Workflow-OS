from __future__ import annotations

import hashlib
import hmac
import json
import re
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from .audit import AuditRevenueLedger
from .ledger import OpportunityLedger
from .opportunities import evaluate, normalize
from .sqlite_lifecycle import managed_connection

MAX_REQUEST_BYTES = 64 * 1024
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class LocalIngestService:
    """Authenticated, loopback-only Opportunity Manager ingest boundary.

    Requests are durably idempotent before any externally visible response. An
    interrupted first attempt is left in PROCESSING and fails closed on retry;
    it must be reconciled rather than guessed successful.
    """

    def __init__(self, db_path: str | Path, token: str):
        if len(token) < 32:
            raise ValueError("ingest token must be at least 32 characters")
        self.db_path = str(db_path)
        self.token = token
        self.opportunities = OpportunityLedger(self.db_path)
        self.audit = AuditRevenueLedger(self.db_path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, timeout=5.0)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout = 5000")
        return db

    def _init_schema(self) -> None:
        with managed_connection(self._connect()) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS ingest_requests (
                    idempotency_key TEXT PRIMARY KEY,
                    payload_sha256 TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('PROCESSING','SUCCEEDED')),
                    response_json TEXT,
                    opportunity_id TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

    def authorized(self, authorization: str | None) -> bool:
        if not authorization or not authorization.startswith("Bearer "):
            return False
        supplied = authorization[7:]
        return hmac.compare_digest(supplied, self.token)

    def ingest(self, idempotency_key: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not _IDEMPOTENCY_RE.fullmatch(idempotency_key):
            raise ValueError("invalid Idempotency-Key")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(encoded) > MAX_REQUEST_BYTES:
            raise ValueError("request payload exceeds 64 KiB")
        digest = hashlib.sha256(encoded).hexdigest()

        with managed_connection(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM ingest_requests WHERE idempotency_key=?", (idempotency_key,)).fetchone()
            if row:
                if row["payload_sha256"] != digest:
                    raise ValueError("Idempotency-Key is already bound to different payload")
                if row["state"] == "SUCCEEDED" and row["response_json"]:
                    return json.loads(row["response_json"])
                raise RuntimeError("ingest request outcome is unresolved and requires reconciliation")
            db.execute(
                "INSERT INTO ingest_requests(idempotency_key,payload_sha256,state) VALUES(?,?,'PROCESSING')",
                (idempotency_key, digest),
            )

        normalized = normalize(payload)
        decision = evaluate(normalized)
        self.opportunities.record(normalized, decision)
        response = {
            "opportunity_id": normalized["opportunity_id"],
            "decision": decision.decision,
            "eligible_for_queue": decision.eligible_for_queue,
            "priority_score": decision.priority_score,
            "requires_revalidation": decision.requires_revalidation,
            "revalidation_fields": list(decision.revalidation_fields),
        }
        response_json = json.dumps(response, sort_keys=True, separators=(",", ":"))
        event_id = "ingest:" + hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        self.audit.append_event(
            event_id,
            "opportunity.ingested",
            {"payload_sha256": digest, "decision": response},
            subject_id=normalized["opportunity_id"],
            occurred_at=decision.evaluated_at,
        )
        with managed_connection(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            changed = db.execute(
                "UPDATE ingest_requests SET state='SUCCEEDED',response_json=?,opportunity_id=?,updated_at=CURRENT_TIMESTAMP WHERE idempotency_key=? AND state='PROCESSING'",
                (response_json, normalized["opportunity_id"], idempotency_key),
            ).rowcount
            if changed != 1:
                raise RuntimeError("ingest request state changed unexpectedly")
        return response


def make_server(service: LocalIngestService, host: str = "127.0.0.1", port: int = 0) -> HTTPServer:
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ValueError("ingest API may only bind to loopback")

    class Handler(BaseHTTPRequestHandler):
        server_version = "WorkflowOSIngest/1"

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _reply(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path == "/health":
                self._reply(200, {"status": "ok"})
            else:
                self._reply(404, {"error": "not_found"})

        def do_POST(self) -> None:
            if self.path != "/v1/opportunities":
                self._reply(404, {"error": "not_found"})
                return
            if not service.authorized(self.headers.get("Authorization")):
                # Drain only a syntactically valid, already-bounded request body.
                # Leaving unread bytes on a loopback socket can intermittently
                # surface as WSAECONNABORTED on Windows before the 401 arrives.
                if not self.headers.get("Transfer-Encoding"):
                    raw_length = self.headers.get("Content-Length")
                    try:
                        length = int(raw_length) if raw_length is not None else -1
                    except ValueError:
                        length = -1
                    if 0 <= length <= MAX_REQUEST_BYTES:
                        self.rfile.read(length)
                self._reply(401, {"error": "unauthorized"})
                return
            if self.headers.get("Transfer-Encoding"):
                self._reply(400, {"error": "transfer_encoding_not_allowed"})
                return
            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                self._reply(411, {"error": "content_length_required"})
                return
            try:
                length = int(raw_length)
            except ValueError:
                self._reply(400, {"error": "invalid_content_length"})
                return
            if length < 0 or length > MAX_REQUEST_BYTES:
                self._reply(413, {"error": "payload_too_large"})
                return
            if self.headers.get_content_type() != "application/json":
                # Drain only the already-bounded request body before replying. On
                # Windows, closing a socket with unread request bytes can surface as
                # WSAECONNABORTED at the local client before it receives the 415.
                self.rfile.read(length)
                self._reply(415, {"error": "application_json_required"})
                return
            body = self.rfile.read(length)
            if len(body) != length:
                self._reply(400, {"error": "incomplete_body"})
                return
            try:
                payload = json.loads(body)
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._reply(400, {"error": "invalid_json"})
                return
            if not isinstance(payload, dict):
                self._reply(400, {"error": "json_object_required"})
                return
            key = self.headers.get("Idempotency-Key") or ""
            try:
                result = service.ingest(key, payload)
            except ValueError as exc:
                self._reply(400, {"error": str(exc)})
                return
            except RuntimeError as exc:
                self._reply(409, {"error": str(exc)})
                return
            self._reply(200, result)

    return HTTPServer((host, port), Handler)
