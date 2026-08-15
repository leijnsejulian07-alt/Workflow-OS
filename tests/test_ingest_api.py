from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path

from workflow_os.ingest import LocalIngestService, MAX_REQUEST_BYTES, make_server

TOKEN = "t" * 32


def valid_payload() -> dict:
    return {
        "source_platform": "test-platform",
        "campaign_id": "campaign-1",
        "title": "Verified test opportunity",
        "category": "content_reward",
        "usage_rights": "campaign grants production and publication rights",
        "rights_verification_state": "VERIFIED",
        "compliance_risk": "LOW",
        "platform_risk": "LOW",
        "duplicate_conflict_status": "CLEAR",
        "user_attention_requirement": "NONE",
        "expected_owner_minutes": 0,
        "expected_production_cost": 1,
        "expected_revenue": 100,
        "estimated_success_probability": 0.5,
        "probability_collection": 1,
        "expected_laptop_minutes": 30,
        "expected_time_to_cash_hours": 48,
        "automation_completeness": 1,
        "capital_required": 0,
        "source_checked_at": datetime.now(timezone.utc).isoformat(),
        "freshness_ttl_seconds": 86400,
        "deadline": "2026-08-31T23:59:59+00:00",
        "remaining_budget": 1000,
        "payout_formula": "EUR 100 per approved unit",
    }


class IngestServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "workflow.db"
        self.service = LocalIngestService(self.db, TOKEN)

    def tearDown(self):
        self.tmp.cleanup()

    def test_token_must_be_strong_enough(self):
        with self.assertRaises(ValueError):
            LocalIngestService(self.db, "short")

    def test_idempotent_replay_returns_same_response(self):
        payload = valid_payload()
        first = self.service.ingest("adapter:test:1", payload)
        second = self.service.ingest("adapter:test:1", payload)
        self.assertEqual(first, second)
        self.assertEqual(first["decision"], "ACCEPT")
        self.assertTrue(first["eligible_for_queue"])
        self.assertEqual(len(self.service.opportunities.queue_candidates()), 1)
        self.assertTrue(self.service.audit.verify_audit_chain())

    def test_idempotency_key_cannot_change_payload(self):
        self.service.ingest("adapter:test:2", valid_payload())
        changed = valid_payload()
        changed["title"] = "different"
        with self.assertRaises(ValueError):
            self.service.ingest("adapter:test:2", changed)

    def test_invalid_key_rejected(self):
        with self.assertRaises(ValueError):
            self.service.ingest("bad key", valid_payload())

    def test_service_payload_limit(self):
        payload = valid_payload()
        payload["source_assets"] = ["x" * MAX_REQUEST_BYTES]
        with self.assertRaises(ValueError):
            self.service.ingest("adapter:test:3", payload)


class HttpBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        service = LocalIngestService(Path(self.tmp.name) / "workflow.db", TOKEN)
        self.server = make_server(service, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.tmp.cleanup()

    def request(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        data = json.loads(response.read())
        conn.close()
        return response.status, data

    def test_loopback_only_binding(self):
        service = LocalIngestService(Path(self.tmp.name) / "other.db", TOKEN)
        with self.assertRaises(ValueError):
            make_server(service, host="0.0.0.0", port=0)

    def test_health_is_minimal(self):
        status, data = self.request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(data, {"status": "ok"})

    def test_post_requires_authentication(self):
        body = json.dumps(valid_payload()).encode()
        status, data = self.request(
            "POST", "/v1/opportunities", body,
            {"Content-Type": "application/json", "Idempotency-Key": "http:1"},
        )
        self.assertEqual(status, 401)
        self.assertEqual(data["error"], "unauthorized")

    def test_authenticated_post_ingests_opportunity(self):
        body = json.dumps(valid_payload()).encode()
        headers = {
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
            "Idempotency-Key": "http:2",
        }
        status, data = self.request("POST", "/v1/opportunities", body, headers)
        self.assertEqual(status, 200)
        self.assertEqual(data["decision"], "ACCEPT")
        self.assertTrue(data["eligible_for_queue"])
        self.assertIn("opportunity_id", data)

    def test_wrong_content_type_rejected(self):
        headers = {
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "text/plain",
            "Idempotency-Key": "http:3",
        }
        status, _ = self.request("POST", "/v1/opportunities", b"{}", headers)
        self.assertEqual(status, 415)

    def test_oversized_content_length_rejected_without_reading_body(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        conn.putrequest("POST", "/v1/opportunities")
        conn.putheader("Authorization", f"Bearer {TOKEN}")
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Idempotency-Key", "http:4")
        conn.putheader("Content-Length", str(MAX_REQUEST_BYTES + 1))
        conn.endheaders()
        response = conn.getresponse()
        self.assertEqual(response.status, 413)
        response.read()
        conn.close()


if __name__ == "__main__":
    unittest.main()
