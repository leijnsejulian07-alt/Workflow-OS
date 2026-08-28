import unittest

from workflow_os.adapters.public_clipping import (
    normalize_clipping_net_campaign,
    normalize_public_clipping_campaign,
    normalize_vues_campaign,
)


def payload(platform: str):
    host = "clipping.net" if platform == "clipping_net" else "vues.app"
    return {
        "source_platform": platform,
        "campaign_id": f"{platform}-campaign-1",
        "title": "Public clipping campaign",
        "canonical_url": f"https://{host}/campaigns/example",
        "observed_at": "2026-08-28T20:00:00Z",
        "raw_evidence_sha256": "a" * 64,
        "remaining_budget": 1000,
        "cpm": 2.5,
        "currency": "USD",
        "allowed_platforms": ["tiktok", "instagram", "youtube"],
        "usage_rights": None,
    }


class PublicClippingAdapterTests(unittest.TestCase):
    def test_clipping_net_preserves_public_evidence_but_blocks_execution(self):
        record = normalize_clipping_net_campaign(payload("clipping_net"))
        self.assertEqual(record.source_platform, "clipping_net")
        self.assertEqual(record.fields["remaining_budget"], 1000)
        self.assertEqual(record.fields["cpm"], 2.5)
        self.assertFalse(record.fields["machine_submission_verified"])
        self.assertFalse(record.fields["zero_touch_execution_enabled"])
        self.assertFalse(record.fields["payout_receipt_verified"])

    def test_vues_preserves_public_evidence_but_blocks_execution(self):
        record = normalize_vues_campaign(payload("vues"))
        self.assertEqual(record.source_platform, "vues")
        self.assertEqual(record.fields["currency"], "USD")
        self.assertIsNone(record.fields["usage_rights"])
        self.assertFalse(record.fields["machine_submission_verified"])
        self.assertFalse(record.fields["zero_touch_execution_enabled"])
        self.assertFalse(record.fields["payout_receipt_verified"])

    def test_hostile_remote_capabilities_are_overridden(self):
        candidate = payload("vues")
        candidate["machine_submission_verified"] = True
        candidate["zero_touch_execution_enabled"] = True
        candidate["payout_receipt_verified"] = True
        candidate["execution_block_reason"] = None

        record = normalize_vues_campaign(candidate)
        self.assertFalse(record.fields["machine_submission_verified"])
        self.assertFalse(record.fields["zero_touch_execution_enabled"])
        self.assertFalse(record.fields["payout_receipt_verified"])
        self.assertEqual(
            record.fields["execution_block_reason"],
            "official_creator_machine_submission_interface_not_verified",
        )

    def test_rejects_invalid_commercial_numbers(self):
        for key, value in (
            ("headline_budget", -1),
            ("remaining_budget", float("inf")),
            ("cpm", "2.00"),
            ("minimum_views", True),
            ("payout_per_1000_views", -0.01),
        ):
            with self.subTest(key=key):
                bad = payload("clipping_net")
                bad[key] = value
                with self.assertRaises(ValueError):
                    normalize_clipping_net_campaign(bad)

    def test_rejects_wrong_host_source_or_platform(self):
        wrong_host = payload("vues")
        wrong_host["canonical_url"] = "https://example.invalid/campaign"
        with self.assertRaises(ValueError):
            normalize_vues_campaign(wrong_host)

        wrong_source = payload("clipping_net")
        wrong_source["source_platform"] = "vues"
        with self.assertRaises(ValueError):
            normalize_clipping_net_campaign(wrong_source)

        with self.assertRaises(ValueError):
            normalize_public_clipping_campaign("unknown", payload("vues"))

    def test_rejects_malformed_evidence_hash(self):
        bad = payload("vues")
        bad["raw_evidence_sha256"] = "not-a-hash"
        with self.assertRaises(ValueError):
            normalize_vues_campaign(bad)


if __name__ == "__main__":
    unittest.main()
