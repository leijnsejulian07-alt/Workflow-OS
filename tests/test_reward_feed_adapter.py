import unittest
from datetime import datetime, timedelta, timezone

from workflow_os.adapters.contracts import AccessMode, SourcePolicy
from workflow_os.adapters.reward_feed import normalize_reward_record


POLICY = SourcePolicy(
    source_platform="example-rewards",
    allowed_hosts=frozenset({"rewards.example.com"}),
    access_mode=AccessMode.AUTHORIZED_ACCOUNT,
)


def valid_payload():
    return {
        "source_platform": "example-rewards",
        "campaign_id": "campaign-123",
        "title": "Creator reward",
        "canonical_url": "https://rewards.example.com/campaigns/123",
        "observed_at": "2026-08-19T20:00:00Z",
        "raw_evidence_sha256": "a" * 64,
        "payout_formula": None,
        "usage_rights": None,
    }


class RewardFeedAdapterTests(unittest.TestCase):
    def test_normalizes_without_inventing_unknown_commercial_or_rights_facts(self):
        record = normalize_reward_record(POLICY, valid_payload())
        self.assertEqual(record.source_platform, "example-rewards")
        self.assertIsNone(record.fields["payout_formula"])
        self.assertIsNone(record.fields["usage_rights"])

    def test_rejects_missing_or_untrusted_identity_evidence(self):
        cases = [
            ("campaign_id", ""),
            ("title", None),
            ("raw_evidence_sha256", "A" * 64),
            ("raw_evidence_sha256", "a" * 63),
            ("canonical_url", "http://rewards.example.com/campaigns/123"),
            ("canonical_url", "https://evil.example/campaigns/123"),
            ("observed_at", "not-a-time"),
            ("observed_at", "2026-08-19T20:00:00"),
        ]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                payload = valid_payload()
                payload[key] = value
                with self.assertRaises(ValueError):
                    normalize_reward_record(POLICY, payload)

    def test_rejects_implausibly_future_observation(self):
        payload = valid_payload()
        payload["observed_at"] = (
            datetime.now(timezone.utc) + timedelta(hours=1)
        ).isoformat()
        with self.assertRaises(ValueError):
            normalize_reward_record(POLICY, payload)

    def test_rejects_remote_source_impersonation(self):
        payload = valid_payload()
        payload["source_platform"] = "other-platform"
        with self.assertRaises(ValueError):
            normalize_reward_record(POLICY, payload)

    def test_rejects_oversized_and_deep_extra_evidence(self):
        oversized = valid_payload()
        oversized["brief"] = "x" * 8_193
        with self.assertRaises(ValueError):
            normalize_reward_record(POLICY, oversized)

        deep = valid_payload()
        deep["nested"] = {"a": {"b": {"c": {"d": "too deep"}}}}
        with self.assertRaises(ValueError):
            normalize_reward_record(POLICY, deep)

    def test_accepts_bounded_structured_extra_evidence(self):
        payload = valid_payload()
        payload["allowed_countries"] = ["NL", "BE"]
        payload["source_assets"] = {"count": 2, "verified": False}
        record = normalize_reward_record(POLICY, payload)
        self.assertEqual(record.fields["allowed_countries"], ["NL", "BE"])
        self.assertEqual(record.fields["source_assets"], {"count": 2, "verified": False})


if __name__ == "__main__":
    unittest.main()
