import unittest
from datetime import datetime, timedelta, timezone

from workflow_os.trading_provider_rules import (
    assess_provider_readiness,
    normalize_provider_rule_evidence,
)


def _rules(**overrides):
    raw = {
        "provider": "tradeify",
        "program": "growth-25k",
        "account_size": 25_000,
        "account_currency": "USD",
        "purchase_cost": 99,
        "rule_version": "2026-08-25",
        "checked_at": "2026-08-25T12:00:00+00:00",
        "official_source_urls": [
            "https://help.tradeify.co/en/articles/10468318-guidelines-for-traders",
            "https://help.tradeify.co/en/articles/10495915-growth-evaluation-accounts",
        ],
        "evidence_sha256": "c" * 64,
        "automation_state": "CONDITIONAL",
        "automation_requires_written_approval": False,
        "execution_access_state": "UNVERIFIED",
        "daily_loss_limit": 600,
        "max_drawdown": 1_000,
        "max_position_contracts": 1,
        "payout_share_pct": 90,
        "prohibited_strategies": ["HFT", "HEDGING"],
        "restricted_times": ["WEEKEND"],
        "production_enabled": False,
    }
    raw.update(overrides)
    return raw


class TradingProviderRuleTests(unittest.TestCase):
    def test_tradeify_style_profile_normalizes_without_live_authority(self):
        evidence = normalize_provider_rule_evidence(_rules())

        self.assertEqual(evidence.provider, "tradeify")
        self.assertEqual(evidence.account_currency, "USD")
        self.assertEqual(evidence.daily_loss_limit, 600)
        self.assertFalse(evidence.production_enabled)

    def test_profile_rejects_non_https_or_credentialed_rule_sources(self):
        with self.assertRaisesRegex(ValueError, "credential-free HTTPS"):
            normalize_provider_rule_evidence(
                _rules(official_source_urls=["http://example.com/rules"])
            )
        with self.assertRaisesRegex(ValueError, "credential-free HTTPS"):
            normalize_provider_rule_evidence(
                _rules(official_source_urls=["https://user:secret@example.com/rules"])
            )

    def test_unknown_automation_and_unverified_execution_fail_closed(self):
        evidence = normalize_provider_rule_evidence(
            _rules(automation_state="UNKNOWN", execution_access_state="UNVERIFIED")
        )
        decision = assess_provider_readiness(
            evidence,
            now=datetime(2026, 8, 25, 13, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(decision.decision, "HOLD")
        self.assertFalse(decision.may_prepare_live_execution)
        self.assertIn("AUTOMATION_NOT_ALLOWED_OR_UNKNOWN", decision.reasons)
        self.assertIn("OFFICIAL_EXECUTION_ACCESS_NOT_VERIFIED", decision.reasons)

    def test_stale_rules_block_preparation(self):
        evidence = normalize_provider_rule_evidence(
            _rules(
                checked_at="2026-08-01T12:00:00+00:00",
                automation_state="ALLOWED",
                execution_access_state="VERIFIED",
                production_enabled=True,
            )
        )
        decision = assess_provider_readiness(
            evidence,
            now=datetime(2026, 8, 25, 13, 0, tzinfo=timezone.utc),
            max_rule_age=timedelta(days=7),
        )

        self.assertEqual(decision.decision, "HOLD")
        self.assertIn("RULE_EVIDENCE_STALE", decision.reasons)

    def test_conditional_automation_can_require_independent_written_approval(self):
        evidence = normalize_provider_rule_evidence(
            _rules(
                automation_state="CONDITIONAL",
                automation_requires_written_approval=True,
                execution_access_state="VERIFIED",
                production_enabled=True,
            )
        )
        decision = assess_provider_readiness(
            evidence,
            now=datetime(2026, 8, 25, 13, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(decision.decision, "HOLD")
        self.assertIn("WRITTEN_AUTOMATION_APPROVAL_NOT_VERIFIED", decision.reasons)

        approved = assess_provider_readiness(
            evidence,
            now=datetime(2026, 8, 25, 13, 0, tzinfo=timezone.utc),
            written_automation_approval_verified=True,
        )
        self.assertEqual(approved.decision, "PREPARE_ONLY")
        self.assertTrue(approved.may_prepare_live_execution)

    def test_even_all_green_provider_rules_only_reach_prepare_only(self):
        evidence = normalize_provider_rule_evidence(
            _rules(
                automation_state="ALLOWED",
                execution_access_state="VERIFIED",
                production_enabled=True,
            )
        )
        decision = assess_provider_readiness(
            evidence,
            now=datetime(2026, 8, 25, 13, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(decision.decision, "PREPARE_ONLY")
        self.assertTrue(decision.may_prepare_live_execution)
        self.assertIn("ORDER_EXECUTION_NOT_AUTHORIZED_BY_PROVIDER_PROFILE", decision.reasons)


if __name__ == "__main__":
    unittest.main()
