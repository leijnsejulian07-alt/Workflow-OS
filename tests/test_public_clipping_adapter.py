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


def clipping_net_non_money_payload():
    candidate = payload("clipping_net")
    for key in ("headline_budget", "remaining_budget", "cpm", "payout_per_1000_views"):
        candidate.pop(key, None)
    candidate.pop("currency", None)
    return candidate


class PublicClippingAdapterTests(unittest.TestCase):
    def test_clipping_net_preserves_public_evidence_but_blocks_execution(self):
        record = normalize_clipping_net_campaign(clipping_net_non_money_payload())
        self.assertEqual(record.source_platform, "clipping_net")
        self.assertEqual(record.title, "Public clipping campaign")
        self.assertNotIn("currency", record.fields)
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
            ("payout_per_1000_views", -0.01),
        ):
            with self.subTest(key=key):
                bad = payload("vues")
                bad[key] = value
                with self.assertRaises(ValueError):
                    normalize_vues_campaign(bad)

    def test_commercial_numbers_are_precision_and_size_bounded(self):
        for key in ("headline_budget", "remaining_budget", "cpm", "payout_per_1000_views"):
            for value in (0.001, 1_000_000_000.01, 10**30, 10**1000, float("nan")):
                with self.subTest(key=key, value=value):
                    bad = payload("vues")
                    bad[key] = value
                    with self.assertRaises(ValueError):
                        normalize_vues_campaign(bad)

        boundary = payload("vues")
        boundary["remaining_budget"] = 1_000_000_000
        record = normalize_vues_campaign(boundary)
        self.assertEqual(record.fields["remaining_budget"], 1_000_000_000)

    def test_money_fields_require_explicit_valid_currency(self):
        for value in (None, "usd", "US", "USDD", "U1D", "€UR", 123, True):
            with self.subTest(currency=value):
                bad = payload("vues")
                if value is None:
                    bad.pop("currency")
                else:
                    bad["currency"] = value
                with self.assertRaises(ValueError):
                    normalize_vues_campaign(bad)

        valid = payload("vues")
        valid["currency"] = "USD"
        record = normalize_vues_campaign(valid)
        self.assertEqual(record.fields["currency"], "USD")

    def test_money_currency_is_source_specific_and_semantically_bounded(self):
        fake = payload("vues")
        fake["currency"] = "ZZZ"
        with self.assertRaises(ValueError):
            normalize_vues_campaign(fake)

        wrong_vues_currency = payload("vues")
        wrong_vues_currency["currency"] = "EUR"
        with self.assertRaises(ValueError):
            normalize_vues_campaign(wrong_vues_currency)

        clipping_money = payload("clipping_net")
        clipping_money["currency"] = "USD"
        with self.assertRaises(ValueError):
            normalize_clipping_net_campaign(clipping_money)

        clipping_eur = payload("clipping_net")
        clipping_eur["currency"] = "EUR"
        with self.assertRaises(ValueError):
            normalize_clipping_net_campaign(clipping_eur)

    def test_currency_without_money_must_still_be_source_supported(self):
        vues_non_money = payload("vues")
        for key in ("headline_budget", "remaining_budget", "cpm", "payout_per_1000_views"):
            vues_non_money.pop(key, None)
        vues_non_money["currency"] = "ZZZ"
        with self.assertRaises(ValueError):
            normalize_vues_campaign(vues_non_money)

        clipping_non_money = clipping_net_non_money_payload()
        clipping_non_money["currency"] = "USD"
        with self.assertRaises(ValueError):
            normalize_clipping_net_campaign(clipping_non_money)

        vues_without_currency = payload("vues")
        for key in ("headline_budget", "remaining_budget", "cpm", "payout_per_1000_views"):
            vues_without_currency.pop(key, None)
        vues_without_currency.pop("currency")
        record = normalize_vues_campaign(vues_without_currency)
        self.assertNotIn("currency", record.fields)

    def test_minimum_views_requires_bounded_nonnegative_integer(self):
        for value in (True, -1, 12.5, "1000", 1_000_000_001):
            with self.subTest(value=value):
                bad = payload("vues")
                bad["minimum_views"] = value
                with self.assertRaises(ValueError):
                    normalize_vues_campaign(bad)

        valid = payload("vues")
        valid["minimum_views"] = 1_000_000_000
        record = normalize_vues_campaign(valid)
        self.assertEqual(record.fields["minimum_views"], 1_000_000_000)

    def test_rejects_wrong_host_source_or_platform(self):
        wrong_host = payload("vues")
        wrong_host["canonical_url"] = "https://example.invalid/campaign"
        with self.assertRaises(ValueError):
            normalize_vues_campaign(wrong_host)

        wrong_source = clipping_net_non_money_payload()
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
