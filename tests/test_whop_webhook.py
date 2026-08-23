from __future__ import annotations

import base64
import hashlib
import hmac
import json
import unittest
from datetime import datetime, timezone

from workflow_os.adapters.whop_webhook import MAX_WEBHOOK_BODY_BYTES, verify_whop_webhook


class WhopWebhookVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.secret = "ws_0123456789abcdef0123456789abcdef"
        self.webhook_id = "msg_test_123"
        self.timestamp = 1787452800
        self.now = datetime.fromtimestamp(self.timestamp, tz=timezone.utc)
        self.payload = {
            "id": self.webhook_id,
            "type": "payment.succeeded",
            "api_version": "v1",
            "timestamp": "2026-08-23T00:00:00Z",
            "account_id": "biz_test",
            "data": {"id": "pay_test"},
        }

    def _request(self, payload: dict[str, object] | None = None) -> tuple[bytes, dict[str, str]]:
        raw = json.dumps(payload or self.payload, separators=(",", ":")).encode("utf-8")
        signed = f"{self.webhook_id}.{self.timestamp}.".encode("ascii") + raw
        signature = base64.b64encode(
            hmac.new(self.secret.encode("utf-8"), signed, hashlib.sha256).digest()
        ).decode("ascii")
        return raw, {
            "Webhook-Id": self.webhook_id,
            "Webhook-Timestamp": str(self.timestamp),
            "Webhook-Signature": f"v1,{signature}",
        }

    def test_valid_signature_returns_bounded_verified_event(self) -> None:
        raw, headers = self._request()
        event = verify_whop_webhook(raw, headers, secret=self.secret, now=self.now)

        self.assertEqual(event.event_id, self.webhook_id)
        self.assertEqual(event.event_type, "payment.succeeded")
        self.assertEqual(event.account_id, "biz_test")
        self.assertEqual(event.data["id"], "pay_test")
        self.assertEqual(event.payload_sha256, hashlib.sha256(raw).hexdigest())
        self.assertEqual(event.occurred_at, "2026-08-23T00:00:00+00:00")

    def test_body_mutation_is_rejected(self) -> None:
        raw, headers = self._request()
        mutated = raw.replace(b"pay_test", b"pay_fake")
        with self.assertRaisesRegex(ValueError, "invalid Whop webhook signature"):
            verify_whop_webhook(mutated, headers, secret=self.secret, now=self.now)

    def test_replay_window_is_enforced_before_payload_use(self) -> None:
        raw, headers = self._request()
        late = datetime.fromtimestamp(self.timestamp + 301, tz=timezone.utc)
        with self.assertRaisesRegex(ValueError, "outside replay window"):
            verify_whop_webhook(raw, headers, secret=self.secret, now=late)

    def test_body_event_id_must_match_signed_header(self) -> None:
        payload = dict(self.payload)
        payload["id"] = "msg_other"
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        signed = f"{self.webhook_id}.{self.timestamp}.".encode("ascii") + raw
        signature = base64.b64encode(
            hmac.new(self.secret.encode("utf-8"), signed, hashlib.sha256).digest()
        ).decode("ascii")
        headers = {
            "webhook-id": self.webhook_id,
            "webhook-timestamp": str(self.timestamp),
            "webhook-signature": f"v1,{signature}",
        }
        with self.assertRaisesRegex(ValueError, "does not match webhook-id"):
            verify_whop_webhook(raw, headers, secret=self.secret, now=self.now)

    def test_malformed_signature_fails_closed(self) -> None:
        raw, headers = self._request()
        headers["Webhook-Signature"] = "v1,%%%not-base64%%%"
        with self.assertRaisesRegex(ValueError, "invalid Whop webhook signature"):
            verify_whop_webhook(raw, headers, secret=self.secret, now=self.now)

    def test_oversized_body_fails_before_verification(self) -> None:
        raw = b"x" * (MAX_WEBHOOK_BODY_BYTES + 1)
        headers = {
            "webhook-id": self.webhook_id,
            "webhook-timestamp": str(self.timestamp),
            "webhook-signature": "v1,AAAA",
        }
        with self.assertRaisesRegex(ValueError, "exceeds allowed size"):
            verify_whop_webhook(raw, headers, secret=self.secret, now=self.now)

    def test_naive_now_is_rejected(self) -> None:
        raw, headers = self._request()
        with self.assertRaisesRegex(ValueError, "now must be timezone-aware"):
            verify_whop_webhook(
                raw,
                headers,
                secret=self.secret,
                now=datetime(2026, 8, 23, 0, 0, 0),
            )

    def test_verified_non_object_data_is_rejected(self) -> None:
        payload = dict(self.payload)
        payload["data"] = ["unexpected"]
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        signed = f"{self.webhook_id}.{self.timestamp}.".encode("ascii") + raw
        signature = base64.b64encode(
            hmac.new(self.secret.encode("utf-8"), signed, hashlib.sha256).digest()
        ).decode("ascii")
        headers = {
            "webhook-id": self.webhook_id,
            "webhook-timestamp": str(self.timestamp),
            "webhook-signature": f"v1,{signature}",
        }
        with self.assertRaisesRegex(ValueError, "webhook data must be an object"):
            verify_whop_webhook(raw, headers, secret=self.secret, now=self.now)


if __name__ == "__main__":
    unittest.main()
