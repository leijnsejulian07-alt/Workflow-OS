from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .db import audit, connect, init_db
from .opportunities import canonical_json, evaluate, normalize, utcnow

DB_PATH = Path(os.environ.get("WORKFLOW_OS_DB", "data/workflow_os.db"))
API_KEY = os.environ.get("WORKFLOW_OS_API_KEY", "")


def persist(raw: dict) -> dict:
    op = normalize(raw)
    decision = evaluate(op)
    op["status"] = "ACCEPTED" if decision.accepted else "REJECTED"
    now = utcnow()
    with connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO opportunities(
              opportunity_id,source_platform,campaign_id,title,category,raw_json,normalized_json,status,
              rejection_reason,expected_collectible_revenue,expected_production_cost,expected_net_profit,
              expected_laptop_minutes,expected_profit_per_laptop_hour,rights_verification_state,
              compliance_risk,platform_risk,user_attention_requirement,source_checked_at,
              freshness_ttl_seconds,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(opportunity_id) DO UPDATE SET
              raw_json=excluded.raw_json,normalized_json=excluded.normalized_json,status=excluded.status,
              rejection_reason=excluded.rejection_reason,expected_collectible_revenue=excluded.expected_collectible_revenue,
              expected_production_cost=excluded.expected_production_cost,expected_net_profit=excluded.expected_net_profit,
              expected_laptop_minutes=excluded.expected_laptop_minutes,
              expected_profit_per_laptop_hour=excluded.expected_profit_per_laptop_hour,
              rights_verification_state=excluded.rights_verification_state,compliance_risk=excluded.compliance_risk,
              platform_risk=excluded.platform_risk,user_attention_requirement=excluded.user_attention_requirement,
              source_checked_at=excluded.source_checked_at,freshness_ttl_seconds=excluded.freshness_ttl_seconds,
              updated_at=excluded.updated_at
            """,
            (
                op["opportunity_id"],op["source_platform"],op.get("campaign_id"),op["title"],op["category"],
                canonical_json(raw),canonical_json(op),op["status"],decision.reason,
                op["expected_collectible_revenue"],op["expected_production_cost"],op["expected_net_profit"],
                op["expected_laptop_minutes"],op["expected_profit_per_laptop_hour"],op["rights_verification_state"],
                op["compliance_risk"],op["platform_risk"],op["user_attention_requirement"],op["source_checked_at"],
                op["freshness_ttl_seconds"],now,now,
            ),
        )
        audit(conn, now, "OPPORTUNITY_EVALUATED", "opportunity", op["opportunity_id"], {"status": op["status"], "reason": decision.reason})
    return {"opportunity": op, "accepted": decision.accepted, "reason": decision.reason}


class Handler(BaseHTTPRequestHandler):
    def _json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, sort_keys=True).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        return bool(API_KEY) and self.headers.get("Authorization") == f"Bearer {API_KEY}"

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json(200, {"ok": True})
            return
        if not self._authorized():
            self._json(401, {"error": "unauthorized"})
            return
        if self.path == "/opportunities":
            with connect(DB_PATH) as conn:
                rows = [dict(r) for r in conn.execute("SELECT * FROM opportunities ORDER BY expected_profit_per_laptop_hour DESC, updated_at DESC")]
            self._json(200, rows)
            return
        self._json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if not self._authorized():
            self._json(401, {"error": "unauthorized"})
            return
        if self.path != "/opportunities":
            self._json(404, {"error": "not_found"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > 1_000_000:
                raise ValueError("invalid body size")
            raw = json.loads(self.rfile.read(size))
            if not isinstance(raw, dict):
                raise ValueError("body must be object")
            result = persist(raw)
            self._json(201 if result["accepted"] else 202, result)
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})

    def log_message(self, format: str, *args) -> None:
        return


def main() -> None:
    if not API_KEY:
        raise SystemExit("WORKFLOW_OS_API_KEY is required")
    init_db(DB_PATH)
    server = ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("WORKFLOW_OS_PORT", "8787"))), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
