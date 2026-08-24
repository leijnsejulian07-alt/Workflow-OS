import unittest

from workflow_os.adapters.whop_bounties import normalize_whop_bounty


class WhopBountiesAdapterTests(unittest.TestCase):
    def _payload(self):
        return {
            "id": "bnty_example123",
            "title": "Create three compliant short-form clips",
            "description": "Use provided source material and follow campaign rules.",
            "status": "published",
            "total_available": 500.0,
            "total_paid": 125.0,
            "currency": "usd",
            "bounty_type": "workforce",
            "vote_threshold": 2,
            "created_at": "2026-08-23T10:00:00Z",
            "updated_at": "2026-08-23T11:00:00Z",
        }

    def _normalize(self, payload=None, **kwargs):
        return normalize_whop_bounty(
            self._payload() if payload is None else payload,
            observed_at="2026-08-23T12:00:00+00:00",
            raw_evidence_sha256="a" * 64,
            **kwargs,
        )

    def test_records_verified_workforce_submission_and_zero_touch_capability(self):
        record = self._normalize()
        self.assertEqual(record.source_platform, "whop_bounties")
        self.assertEqual(record.campaign_id, "bnty_example123")
        self.assertEqual(
            record.canonical_url,
            "https://api.whop.com/api/v1/bounties/bnty_example123",
        )
        self.assertTrue(record.fields["machine_submission_verified"])
        self.assertTrue(record.fields["zero_touch_execution_enabled"])
        self.assertIsNone(record.fields["execution_block_reason"])

    def test_non_workforce_bounty_does_not_inherit_worker_submission_capability(self):
        payload = self._payload()
        payload["bounty_type"] = "classic"
        record = self._normalize(payload)
        self.assertFalse(record.fields["machine_submission_verified"])
        self.assertFalse(record.fields["zero_touch_execution_enabled"])
        self.assertEqual(
            record.fields["execution_block_reason"],
            "official_worker_submission_requires_workforce_bounty",
        )

    def test_accepts_documented_sandbox_host(self):
        record = self._normalize(api_host="sandbox-api.whop.com")
        self.assertTrue(record.canonical_url.startswith("https://sandbox-api.whop.com/"))

    def test_rejects_unapproved_host(self):
        with self.assertRaises(ValueError):
            self._normalize(api_host="evil.example")

    def test_rejects_unknown_lifecycle_status(self):
        payload = self._payload()
        payload["status"] = "mystery"
        with self.assertRaises(ValueError):
            self._normalize(payload)

    def test_rejects_negative_or_nonfinite_funding(self):
        for value in (-1, float("inf"), float("nan"), True):
            payload = self._payload()
            payload["total_available"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self._normalize(payload)

    def test_rejects_invalid_bounty_identity(self):
        payload = self._payload()
        payload["id"] = "campaign_123"
        with self.assertRaises(ValueError):
            self._normalize(payload)

    def test_rejects_invalid_vote_threshold(self):
        for value in (-1, 1.5, True):
            payload = self._payload()
            payload["vote_threshold"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self._normalize(payload)

    def test_remote_payload_cannot_override_local_execution_capability(self):
        payload = self._payload()
        payload["machine_submission_verified"] = False
        payload["zero_touch_execution_enabled"] = False
        payload["execution_block_reason"] = "remote_override"
        record = self._normalize(payload)
        self.assertTrue(record.fields["machine_submission_verified"])
        self.assertTrue(record.fields["zero_touch_execution_enabled"])
        self.assertIsNone(record.fields["execution_block_reason"])


if __name__ == "__main__":
    unittest.main()
