from __future__ import annotations

import unittest
from datetime import datetime, timezone

from workflow_os.trading_provider_rules import normalize_provider_rule_evidence
from workflow_os.trading_provider_selection import select_provider_purchase


NOW = datetime.now(timezone.utc).isoformat()
SHA = "a" * 64


def profile(
    provider: str,
    program: str,
    *,
    cost: float,
    drawdown: float,
    payout: float = 90,
    automation: str = "ALLOWED",
    execution: str = "VERIFIED",
    production: bool = True,
):
    return normalize_provider_rule_evidence(
        {
            "provider": provider,
            "program": program,
            "account_size": 25000,
            "account_currency": "USD",
            "purchase_cost": cost,
            "rule_version": "rules-1",
            "checked_at": NOW,
            "official_source_urls": [f"https://example.com/{provider}/{program}"],
            "evidence_sha256": SHA,
            "automation_state": automation,
            "automation_requires_written_approval": False,
            "execution_access_state": execution,
            "daily_loss_limit": 500,
            "max_drawdown": drawdown,
            "max_position_contracts": 2,
            "payout_share_pct": payout,
            "prohibited_strategies": ["HFT"],
            "restricted_times": [],
            "production_enabled": production,
        }
    )


class ProviderSelectionTests(unittest.TestCase):
    def test_first_account_selects_cheapest_verified_candidate(self):
        decision = select_provider_purchase(
            [
                profile("Alpha", "25K", cost=99, drawdown=1000),
                profile("Beta", "25K", cost=49, drawdown=500),
            ],
            reconciled_cash_available=150,
            stage="FIRST_ACCOUNT",
        )
        self.assertEqual(decision.decision, "OWNER_APPROVAL_REQUIRED")
        self.assertTrue(decision.owner_approval_required)
        self.assertEqual(decision.selected.provider, "Beta")
        self.assertEqual(decision.selected.purchase_cost, 49)

    def test_reinvest_prefers_usable_drawdown_per_cost(self):
        decision = select_provider_purchase(
            [
                profile("Alpha", "25K", cost=100, drawdown=1000),
                profile("Beta", "50K", cost=150, drawdown=2500),
            ],
            reconciled_cash_available=200,
            stage="REINVEST",
        )
        self.assertEqual(decision.selected.provider, "Beta")
        self.assertGreater(
            decision.eligible_candidates[0].usable_drawdown_per_cost,
            decision.eligible_candidates[1].usable_drawdown_per_cost,
        )

    def test_hold_when_only_unverified_or_unaffordable_candidates_exist(self):
        decision = select_provider_purchase(
            [
                profile("Alpha", "25K", cost=50, drawdown=1000, execution="UNVERIFIED"),
                profile("Beta", "25K", cost=500, drawdown=1000),
            ],
            reconciled_cash_available=100,
            stage="FIRST_ACCOUNT",
        )
        self.assertEqual(decision.decision, "HOLD")
        self.assertIsNone(decision.selected)
        self.assertEqual(decision.eligible_candidates, ())

    def test_prohibited_automation_is_never_purchase_eligible(self):
        decision = select_provider_purchase(
            [profile("Alpha", "25K", cost=10, drawdown=1000, automation="PROHIBITED")],
            reconciled_cash_available=100,
            stage="FIRST_ACCOUNT",
        )
        self.assertEqual(decision.decision, "HOLD")
        self.assertIsNone(decision.selected)

    def test_selection_never_auto_approves_spending(self):
        decision = select_provider_purchase(
            [profile("Alpha", "25K", cost=10, drawdown=1000)],
            reconciled_cash_available=100,
            stage="FIRST_ACCOUNT",
        )
        self.assertEqual(decision.decision, "OWNER_APPROVAL_REQUIRED")
        self.assertTrue(decision.owner_approval_required)

    def test_invalid_stage_and_cash_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "stage is invalid"):
            select_provider_purchase([], reconciled_cash_available=100, stage="AUTO_BUY")
        with self.assertRaisesRegex(ValueError, "finite and nonnegative"):
            select_provider_purchase([], reconciled_cash_available=-1, stage="FIRST_ACCOUNT")

    def test_duplicate_provider_program_identity_is_rejected(self):
        duplicate = profile("Alpha", "25K", cost=10, drawdown=1000)
        with self.assertRaisesRegex(ValueError, "must be unique"):
            select_provider_purchase(
                [duplicate, duplicate],
                reconciled_cash_available=100,
                stage="FIRST_ACCOUNT",
            )


if __name__ == "__main__":
    unittest.main()
