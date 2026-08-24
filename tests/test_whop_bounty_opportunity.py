from __future__ import annotations

import unittest
from datetime import datetime, timezone

from workflow_os.adapters.contracts import DiscoveryRecord
from workflow_os.opportunities import evaluate, normalize
from workflow_os.whop_bounty_opportunity import (
    TrustedWhopWorkforceEvidence,
    build_whop_workforce_opportunity,
)


class WhopBountyOpportunityTests(unittest.TestCase):
    NOW = datetime(2026, 8, 24, 5, 30, tzinfo=timezone.utc)

    def _record(self, **field_overrides):
        fields = {
            "description": "Create a verified deliverable",
            "status": "published",
            "total_available": 500.0,
            "total_paid": 10.0,
            "currency": "usd",
            "bounty_type": "workforce",
            "vote_threshold": 1,
            "created_at": "2026-08-23T00:00:00+00:00",
            "updated_at": "2026-08-24T05:00:00+00:00",
            "machine_submission_verified": True,
            "zero_touch_execution_enabled": True,
            "execution_block_reason": None,
        }
        fields.update(field_overrides)
        return DiscoveryRecord(
            source_platform="whop_bounties",
            campaign_id="bnty_example123",
            title="Example workforce bounty",
            canonical_url="https://api.whop.com/api/v1/bounties/bnty_example123",
            observed_at="2026-08-24T05:00:00+00:00",
            raw_evidence_sha256="a" * 64,
            fields=fields,
        )

    def _evidence(self, **overrides):
        values = dict(
            rights_verified=True,
            account_authorized=True,
            worker_identity_verified=True,
            campaign_requirements_verified=True,
            deliverable_requirements_verified=True,
            usage_rights="Whop bounty terms authorize this deliverable submission.",
            compliance_risk="LOW",
            platform_risk="LOW",
            duplicate_conflict_status="CLEAR",
            user_attention_requirement="NONE",
            expected_owner_minutes=0.0,
            expected_revenue_eur=100.0,
            expected_production_cost_eur=5.0,
            expected_laptop_minutes=30.0,
            estimated_success_probability=0.8,
            probability_collection=0.9,
            expected_time_to_cash_hours=48.0,
            automation_completeness=1.0,
            capital_required_eur=5.0,
            remaining_budget_eur=200.0,
            payout_cap_eur=100.0,
            payout_formula="EUR 100 for one approved verified submission",
            payment_method="Whop balance then separately reconciled external receipt",
            approval_rules="Submission must satisfy the verified workforce bounty requirements.",
            originality_requirements="Use only assets covered by the verified rights evidence.",
            account_requirements=("authorized Whop worker account",),
            deadline="2026-08-25T12:00:00+00:00",
            freshness_ttl_seconds=3600,
            evidence_sha256="b" * 64,
        )
        values.update(overrides)
        return TrustedWhopWorkforceEvidence(**values)

    def test_builds_payload_that_opportunity_manager_can_accept(self):
        raw = build_whop_workforce_opportunity(self._record(), self._evidence())
        normalized = normalize(raw, now=self.NOW)
        decision = evaluate(normalized, now=self.NOW)

        self.assertEqual(decision.decision, "ACCEPT")
        self.assertTrue(decision.eligible_for_queue)
        self.assertEqual(normalized["campaign_id"], "bnty_example123")
        self.assertEqual(normalized["rights_verification_state"], "VERIFIED")
        self.assertTrue(normalized["zero_touch_execution_enabled"])
        self.assertAlmostEqual(normalized["expected_collectible_revenue"], 72.0)
        self.assertAlmostEqual(normalized["expected_net_profit"], 67.0)

    def test_rejects_non_workforce_discovery(self):
        with self.assertRaises(ValueError):
            build_whop_workforce_opportunity(
                self._record(
                    bounty_type="classic",
                    machine_submission_verified=False,
                    zero_touch_execution_enabled=False,
                    execution_block_reason="official_worker_submission_requires_workforce_bounty",
                ),
                self._evidence(),
            )

    def test_rejects_discovery_that_is_still_execution_blocked(self):
        with self.assertRaises(ValueError):
            build_whop_workforce_opportunity(
                self._record(
                    zero_touch_execution_enabled=False,
                    execution_block_reason="not_verified",
                ),
                self._evidence(),
            )

    def test_remote_discovery_cannot_supply_rights_or_account_authority(self):
        record = self._record(
            rights_verified=True,
            account_authorized=True,
            worker_identity_verified=True,
        )
        for evidence in (
            self._evidence(rights_verified=False),
            self._evidence(account_authorized=False),
            self._evidence(worker_identity_verified=False),
        ):
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                build_whop_workforce_opportunity(record, evidence)

    def test_rejects_economic_claim_above_verified_cap_or_budget(self):
        with self.assertRaises(ValueError):
            build_whop_workforce_opportunity(
                self._record(),
                self._evidence(expected_revenue_eur=101.0),
            )
        with self.assertRaises(ValueError):
            build_whop_workforce_opportunity(
                self._record(),
                self._evidence(expected_revenue_eur=100.0, remaining_budget_eur=99.0),
            )

    def test_rejects_recurring_owner_fulfillment(self):
        with self.assertRaises(ValueError):
            build_whop_workforce_opportunity(
                self._record(),
                self._evidence(expected_owner_minutes=1.0),
            )

    def test_rejects_malformed_trusted_evidence_digest(self):
        with self.assertRaises(ValueError):
            build_whop_workforce_opportunity(
                self._record(),
                self._evidence(evidence_sha256="NOT-A-DIGEST"),
            )

    def test_owner_attention_can_pause_but_not_fake_zero_touch(self):
        raw = build_whop_workforce_opportunity(
            self._record(),
            self._evidence(user_attention_requirement="KYC"),
        )
        decision = evaluate(normalize(raw, now=self.NOW), now=self.NOW)
        self.assertEqual(decision.decision, "PAUSE")
        self.assertFalse(decision.eligible_for_queue)


if __name__ == "__main__":
    unittest.main()
