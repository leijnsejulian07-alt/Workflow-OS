import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workflow_os.experiment_ledger import ExperimentLedger
from workflow_os.ledger import OpportunityLedger
from workflow_os.opportunities import OpportunityDecision
from workflow_os.reconciliation import RevenueReconciliationLedger
from workflow_os.scaling_control import revenue_controlled_queue_candidates, scaling_directive


class ScalingControlTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "workflow-os.sqlite3"
        self.opportunities = OpportunityLedger(self.path)
        self.reconciliation = RevenueReconciliationLedger(self.path)
        self.experiments = ExperimentLedger(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def _record_opportunity(self, opportunity_id: str, *, priority: float = 50.0) -> None:
        opportunity = {
            "opportunity_id": opportunity_id,
            "source_platform": "test-platform",
            "campaign_id": "campaign-1",
            "discovered_at": "2026-08-22T08:00:00+00:00",
        }
        decision = OpportunityDecision(
            opportunity_id=opportunity_id,
            decision="ACCEPT",
            decision_reasons=("ELIGIBLE",),
            eligible_for_queue=True,
            economic_score=25.0,
            priority_score=priority,
            requires_revalidation=False,
            revalidation_fields=(),
            owner_attention_requirement="NONE",
            expected_collectible_revenue=100.0,
            expected_net_profit=80.0,
            expected_profit_per_laptop_hour=40.0,
            estimated_total_cost=20.0,
            risk_penalty=0.0,
            freshness_expires_at="2026-08-22T14:00:00+00:00",
            evaluated_at="2026-08-22T08:01:00+00:00",
        )
        self.opportunities.record(opportunity, decision)

    def _event(self, opportunity_id: str, event_id: str, event_type: str, amount: str) -> None:
        self.reconciliation.record_event(
            platform="test-platform",
            external_event_id=event_id,
            opportunity_id=opportunity_id,
            event_type=event_type,
            amount_eur=amount,
            occurred_at="2026-08-22T09:00:00+00:00",
            evidence_sha256=(event_id[0] if event_id[0] in "abcdef0123456789" else "a") * 64,
        )

    def test_zero_sample_candidate_gets_one_bounded_experiment(self):
        self._record_opportunity("op-1")
        directive = scaling_directive(self.reconciliation, "op-1")
        self.assertEqual(directive.action, "EXPERIMENT")
        self.assertTrue(directive.may_schedule)
        self.assertEqual(directive.max_new_jobs, 1)
        self.assertEqual(directive.sample_count, 0)

    def test_positive_first_sample_keeps_but_does_not_scale(self):
        self._record_opportunity("op-1")
        self._event("op-1", "a1", "CASH_RECEIVED", "20.00")
        self._event("op-1", "b1", "COST_INCURRED", "5.00")
        directive = scaling_directive(self.reconciliation, "op-1")
        self.assertEqual(directive.action, "KEEP")
        self.assertEqual(directive.max_new_jobs, 1)
        self.assertAlmostEqual(directive.realized_profit_eur, 15.0)

    def test_negative_realized_margin_kills_scheduling(self):
        self._record_opportunity("op-1")
        self._event("op-1", "a1", "CASH_RECEIVED", "5.00")
        self._event("op-1", "b1", "COST_INCURRED", "8.00")
        directive = scaling_directive(self.reconciliation, "op-1")
        self.assertEqual(directive.action, "KILL")
        self.assertFalse(directive.may_schedule)
        self.assertEqual(directive.max_new_jobs, 0)

    def test_scale_requires_reconciled_samples_and_profit_floor(self):
        self._record_opportunity("op-1")
        for idx in range(3):
            self._event("op-1", f"a{idx}", "CASH_RECEIVED", "20.00")
        self._event("op-1", "b1", "COST_INCURRED", "10.00")
        directive = scaling_directive(self.reconciliation, "op-1")
        self.assertEqual(directive.action, "SCALE")
        self.assertEqual(directive.max_new_jobs, 2)
        self.assertEqual(directive.sample_count, 3)
        self.assertAlmostEqual(directive.realized_profit_eur, 50.0)

    def test_controlled_queue_filters_killed_opportunity(self):
        self._record_opportunity("op-kill", priority=70.0)
        self._record_opportunity("op-experiment", priority=60.0)
        self._event("op-kill", "a1", "CASH_RECEIVED", "2.00")
        self._event("op-kill", "b1", "COST_INCURRED", "5.00")
        candidates = revenue_controlled_queue_candidates(
            self.opportunities,
            self.reconciliation,
            self.experiments,
            reserved_at="2026-08-22T10:00:00+00:00",
        )
        self.assertEqual([item["opportunity_id"] for item in candidates], ["op-experiment"])
        self.assertEqual(candidates[0]["revenue_control"]["action"], "EXPERIMENT")

    def test_repeated_scheduler_run_cannot_grant_second_first_experiment(self):
        self._record_opportunity("op-1")
        first = revenue_controlled_queue_candidates(
            self.opportunities,
            self.reconciliation,
            self.experiments,
            reserved_at="2026-08-22T10:00:00+00:00",
        )
        second = revenue_controlled_queue_candidates(
            self.opportunities,
            self.reconciliation,
            self.experiments,
            reserved_at="2026-08-22T10:05:00+00:00",
        )
        self.assertEqual([item["opportunity_id"] for item in first], ["op-1"])
        self.assertEqual(second, [])

    def test_realized_evidence_can_schedule_after_experiment_reservation(self):
        self._record_opportunity("op-1")
        revenue_controlled_queue_candidates(
            self.opportunities,
            self.reconciliation,
            self.experiments,
            reserved_at="2026-08-22T10:00:00+00:00",
        )
        self._event("op-1", "a1", "CASH_RECEIVED", "20.00")
        self._event("op-1", "b1", "COST_INCURRED", "5.00")
        candidates = revenue_controlled_queue_candidates(
            self.opportunities,
            self.reconciliation,
            self.experiments,
            reserved_at="2026-08-22T10:10:00+00:00",
        )
        self.assertEqual(candidates[0]["revenue_control"]["action"], "KEEP")

    def test_invalid_job_bounds_fail_closed(self):
        with self.assertRaises(ValueError):
            scaling_directive(self.reconciliation, "op-1", scale_jobs=5)
        with self.assertRaises(ValueError):
            scaling_directive(self.reconciliation, "op-1", keep_jobs=2, scale_jobs=1)


if __name__ == "__main__":
    unittest.main()
