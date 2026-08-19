from __future__ import annotations

import unittest
from datetime import datetime, timezone

from workflow_os.adapters.content_reward_discovery import to_opportunity
from workflow_os.opportunities import evaluate, normalize


def valid_campaign() -> dict:
    return {
        "source_platform": "clip_army",
        "campaign_id": "camp-789",
        "title": "Podcast Clipping Campaign Q3",
        "category": "content_clipping_reward",
        "platforms": ["tiktok", "youtube_shorts", "instagram_reels"],
        "allowed_countries": ["US", "CA", "GB"],
        "source_assets": ["https://cdn.example.com/stream-101.mp4"],
        "usage_rights": "Creator grants full clipping and redistribution rights for monetized campaign clips.",
        "rights_attested": True,
        "rights_verification_state": "VERIFIED",
        "expected_revenue_usd": 150.0,
        "expected_production_cost_usd": 5.0,
        "expected_laptop_minutes": 15.0,
        "estimated_success_probability": 0.85,
        "probability_collection": 0.95,
        "expected_time_to_cash_hours": 24.0,
        "automation_completeness": 0.9,
        "capital_required_usd": 0.0,
        "remaining_budget_usd": 3000.0,
        "payout_cap_usd": 500.0,
        "source_checked_at": "2026-08-18T12:00:00+00:00",
        "deadline": "2026-08-25T23:59:59+00:00",
        "payment_method": "stripe_connect",
        "payout_formula": "USD 150.00 fixed CPM per 10k views",
    }


class ContentRewardDiscoveryAdapterTests(unittest.TestCase):
    def test_valid_campaign_reaches_accept_and_queue_eligible(self):
        raw = to_opportunity(valid_campaign())
        self.assertEqual(raw["rights_verification_state"], "VERIFIED")
        self.assertEqual(raw["category"], "content_clipping_reward")
        self.assertEqual(raw["source_platform"], "content-reward:clip_army")
        self.assertEqual(raw["expected_owner_minutes"], 0)
        self.assertIs(raw["content_reward_evidence"]["read_only_discovery"], True)

        now = datetime(2026, 8, 18, 14, 0, tzinfo=timezone.utc)
        normalized = normalize(raw, now=now)
        decision = evaluate(normalized, now=now)
        self.assertEqual(decision.decision, "ACCEPT")
        self.assertTrue(decision.eligible_for_queue)

    def test_unsupported_source_platform_is_rejected(self):
        camp = valid_campaign()
        camp["source_platform"] = "unauthorized_scraper_api"
        with self.assertRaises(ValueError):
            to_opportunity(camp)

    def test_empty_or_invalid_platforms_rejected(self):
        camp = valid_campaign()
        camp["platforms"] = []
        with self.assertRaises(ValueError):
            to_opportunity(camp)

        camp["platforms"] = ["unsupported_video_host"]
        with self.assertRaises(ValueError):
            to_opportunity(camp)

    def test_missing_usage_rights_is_rejected(self):
        camp = valid_campaign()
        camp["usage_rights"] = ""
        with self.assertRaises(ValueError):
            to_opportunity(camp)

    def test_unknown_rights_state_fails_closed_in_opportunity_manager(self):
        camp = valid_campaign()
        camp["rights_attested"] = False
        camp["rights_verification_state"] = "UNKNOWN"
        raw = to_opportunity(camp)
        self.assertEqual(raw["rights_verification_state"], "UNKNOWN")

        now = datetime(2026, 8, 18, 14, 0, tzinfo=timezone.utc)
        normalized = normalize(raw, now=now)
        decision = evaluate(normalized, now=now)
        self.assertEqual(decision.decision, "REJECT")
        self.assertFalse(decision.eligible_for_queue)
        self.assertIn("RIGHTS_NOT_VERIFIED", decision.decision_reasons)

    def test_non_numeric_or_infinite_economics_are_rejected(self):
        for field, value in (
            ("expected_revenue_usd", "NaN"),
            ("expected_production_cost_usd", "Infinity"),
            ("estimated_success_probability", -0.1),
            ("probability_collection", 1.5),
            ("remaining_budget_usd", float("nan")),
        ):
            with self.subTest(field=field, value=value):
                camp = valid_campaign()
                camp[field] = value
                with self.assertRaises(ValueError):
                    to_opportunity(camp)

    def test_same_campaign_fingerprint_is_idempotent(self):
        id1 = to_opportunity(valid_campaign())["opportunity_id"]
        id2 = to_opportunity(valid_campaign())["opportunity_id"]
        self.assertEqual(id1, id2)


if __name__ == "__main__":
    unittest.main()
