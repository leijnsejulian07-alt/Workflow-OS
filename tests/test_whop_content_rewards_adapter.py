import unittest

from workflow_os.adapters.whop_content_rewards import normalize_whop_content_reward


def payload():
    return {
        "source_platform": "whop_content_rewards",
        "campaign_id": "campaign-example",
        "title": "Example clipping campaign",
        "canonical_url": "https://whop.com/contentrewards/",
        "observed_at": "2026-08-20T11:00:00Z",
        "raw_evidence_sha256": "b" * 64,
        "remaining_budget": None,
        "usage_rights": None,
        "payment_method": None,
        "payout_formula": None,
    }


class WhopContentRewardsAdapterTests(unittest.TestCase):
    def test_reuses_shared_normalizer_and_preserves_unknowns(self):
        record = normalize_whop_content_reward(payload())
        self.assertEqual(record.source_platform, "whop_content_rewards")
        self.assertIsNone(record.fields["remaining_budget"])
        self.assertIsNone(record.fields["usage_rights"])
        self.assertIsNone(record.fields["payment_method"])
        self.assertIsNone(record.fields["payout_formula"])

    def test_rejects_wrong_source_or_host(self):
        wrong_source = payload()
        wrong_source["source_platform"] = "other"
        with self.assertRaises(ValueError):
            normalize_whop_content_reward(wrong_source)

        wrong_host = payload()
        wrong_host["canonical_url"] = "https://example.invalid/campaign"
        with self.assertRaises(ValueError):
            normalize_whop_content_reward(wrong_host)

    def test_rejects_untrusted_evidence_hash(self):
        bad = payload()
        bad["raw_evidence_sha256"] = "not-a-hash"
        with self.assertRaises(ValueError):
            normalize_whop_content_reward(bad)


if __name__ == "__main__":
    unittest.main()
