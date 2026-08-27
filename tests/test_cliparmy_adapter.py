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
        self.assertFalse(record.fields["machine_submission_verified"])
        self.assertFalse(record.fields["zero_touch_execution_enabled"])
        self.assertEqual(
            record.fields["execution_block_reason"],
            "official_creator_machine_submission_interface_not_verified",
        )

    def test_hostile_payload_cannot_enable_zero_touch_submission(self):
        candidate = payload()
        candidate["machine_submission_verified"] = True
        candidate["zero_touch_execution_enabled"] = True
        candidate["execution_block_reason"] = None

        record = normalize_cliparmy_campaign(candidate)

        self.assertFalse(record.fields["machine_submission_verified"])
        self.assertFalse(record.fields["zero_touch_execution_enabled"])
        self.assertEqual(
            record.fields["execution_block_reason"],
            "official_creator_machine_submission_interface_not_verified",
        )

    def test_preserves_explicit_current_campaign_evidence(self):
        candidate = payload()
        candidate.update(
            {
                "headline_budget_eur": 1000,
                "cpm_eur": 2.0,
                "allowed_platforms": ["tiktok", "instagram"],
                "briefing_url": "https://cliparmy.nl/",
                "briefing_evidence_sha256": "b" * 64,
                "usage_rights": "campaign_briefing_required",
            }
        )

        record = normalize_cliparmy_campaign(candidate)

        self.assertEqual(record.fields["headline_budget_eur"], 1000)
        self.assertEqual(record.fields["cpm_eur"], 2.0)
        self.assertEqual(record.fields["allowed_platforms"], ["tiktok", "instagram"])
        self.assertEqual(record.fields["briefing_evidence_sha256"], "b" * 64)
        self.assertEqual(record.fields["usage_rights"], "campaign_briefing_required")

    def test_rejects_invalid_commercial_numbers(self):
        for key, value in (
            ("headline_budget_eur", -1),
            ("remaining_budget", float("inf")),
            ("cpm_eur", "2.00"),
            ("payout_per_1000_views_eur", True),
        ):
            with self.subTest(key=key):
                bad = payload()
                bad[key] = value
                with self.assertRaises(ValueError):
                    normalize_cliparmy_campaign(bad)

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
