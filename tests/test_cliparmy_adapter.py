import unittest

from workflow_os.adapters.cliparmy import normalize_cliparmy_campaign


def payload():
    return {
        "source_platform": "cliparmy",
        "campaign_id": "public-supergaande",
        "title": "Supergaande",
        "canonical_url": "https://cliparmy.nl/",
        "observed_at": "2026-08-20T07:00:00Z",
        "raw_evidence_sha256": "a" * 64,
        "remaining_budget": 400,
        "usage_rights": None,
        "payment_method": None,
        "payout_formula": None,
    }


class ClipArmyAdapterTests(unittest.TestCase):
    def test_reuses_shared_normalizer_and_preserves_unknowns(self):
        record = normalize_cliparmy_campaign(payload())
        self.assertEqual(record.source_platform, "cliparmy")
        self.assertEqual(record.fields["remaining_budget"], 400)
        self.assertIsNone(record.fields["usage_rights"])
        self.assertIsNone(record.fields["payment_method"])
        self.assertIsNone(record.fields["payout_formula"])

    def test_rejects_wrong_source_or_host(self):
        wrong_source = payload()
        wrong_source["source_platform"] = "other"
        with self.assertRaises(ValueError):
            normalize_cliparmy_campaign(wrong_source)

        wrong_host = payload()
        wrong_host["canonical_url"] = "https://example.invalid/campaign"
        with self.assertRaises(ValueError):
            normalize_cliparmy_campaign(wrong_host)

    def test_rejects_untrusted_evidence_hash(self):
        bad = payload()
        bad["raw_evidence_sha256"] = "not-a-hash"
        with self.assertRaises(ValueError):
            normalize_cliparmy_campaign(bad)


if __name__ == "__main__":
    unittest.main()
