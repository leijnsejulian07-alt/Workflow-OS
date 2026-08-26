from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from workflow_os.whop_bounty_settlement_scheduler import (
    schedule_whop_bounty_settlement_feedback,
)


def _directive(*, action: str = "KEEP", may_schedule: bool = True, max_new_jobs: int = 1, sample_count: int = 1):
    return SimpleNamespace(
        opportunity_id="opp-1",
        action=action,
        may_schedule=may_schedule,
        max_new_jobs=max_new_jobs,
        sample_count=sample_count,
        to_dict=lambda: {
            "opportunity_id": "opp-1",
            "action": action,
            "may_schedule": may_schedule,
            "max_new_jobs": max_new_jobs,
            "sample_count": sample_count,
            "realized_cash_eur": 50.0,
            "reconciled_cost_eur": 5.0,
            "realized_profit_eur": 45.0,
            "reasons": ["TEST"],
            "policy_version": "test/1",
        },
    )


def _feedback(directive=None, *, reconciled_id: str = "opp-1", provenance_id: str = "opp-1"):
    return SimpleNamespace(
        scaling=directive or _directive(),
        payout=SimpleNamespace(
            reconciled_event=SimpleNamespace(opportunity_id=reconciled_id),
            provenance=SimpleNamespace(opportunity_id=provenance_id),
        ),
    )


class WhopBountySettlementSchedulerTests(unittest.TestCase):
    def test_keep_schedules_only_exact_paid_opportunity(self):
        opportunities = Mock()
        opportunities.latest_decision.return_value = {
            "opportunity_id": "opp-1",
            "decision": "ACCEPT",
            "eligible_for_queue": True,
        }
        jobs = Mock()
        queued = [SimpleNamespace(job_id="job-1")]
        snapshot = SimpleNamespace(payload={"opportunity_id": "opp-1"}, sha256="a" * 64)

        with patch("workflow_os.whop_bounty_settlement_scheduler.snapshot_opportunity", return_value=snapshot) as snapshot_fn, patch(
            "workflow_os.whop_bounty_settlement_scheduler.enqueue_controlled_candidates",
            return_value=queued,
        ) as enqueue_fn:
            result = schedule_whop_bounty_settlement_feedback(
                opportunities=opportunities,
                jobs=jobs,
                feedback=_feedback(),
                scheduled_at="2026-08-26T19:00:00Z",
            )

        self.assertEqual(result.jobs, tuple(queued))
        opportunities.latest_decision.assert_called_once_with("opp-1")
        snapshot_fn.assert_called_once_with(opportunities, "opp-1")
        candidate = enqueue_fn.call_args.args[1][0]
        self.assertEqual(candidate["opportunity_id"], "opp-1")
        self.assertEqual(candidate["revenue_control"]["action"], "KEEP")
        self.assertEqual(candidate["opportunity_snapshot_sha256"], "a" * 64)

    def test_pause_schedules_nothing(self):
        opportunities = Mock()
        jobs = Mock()
        directive = _directive(action="PAUSE", may_schedule=False, max_new_jobs=0)

        with patch("workflow_os.whop_bounty_settlement_scheduler.snapshot_opportunity") as snapshot_fn, patch(
            "workflow_os.whop_bounty_settlement_scheduler.enqueue_controlled_candidates"
        ) as enqueue_fn:
            result = schedule_whop_bounty_settlement_feedback(
                opportunities=opportunities,
                jobs=jobs,
                feedback=_feedback(directive),
                scheduled_at="2026-08-26T19:00:00Z",
            )

        self.assertEqual(result.jobs, ())
        opportunities.latest_decision.assert_not_called()
        snapshot_fn.assert_not_called()
        enqueue_fn.assert_not_called()

    def test_identity_drift_fails_closed_before_scheduling(self):
        with self.assertRaisesRegex(RuntimeError, "identity mismatch"):
            schedule_whop_bounty_settlement_feedback(
                opportunities=Mock(),
                jobs=Mock(),
                feedback=_feedback(provenance_id="opp-other"),
                scheduled_at="2026-08-26T19:00:00Z",
            )

    def test_ineligible_latest_decision_fails_closed(self):
        opportunities = Mock()
        opportunities.latest_decision.return_value = {
            "opportunity_id": "opp-1",
            "decision": "PAUSE",
            "eligible_for_queue": False,
        }
        with self.assertRaisesRegex(RuntimeError, "no longer eligible"):
            schedule_whop_bounty_settlement_feedback(
                opportunities=opportunities,
                jobs=Mock(),
                feedback=_feedback(),
                scheduled_at="2026-08-26T19:00:00Z",
            )

    def test_experiment_after_settlement_is_rejected(self):
        directive = _directive(action="EXPERIMENT", may_schedule=True, max_new_jobs=1, sample_count=1)
        with self.assertRaisesRegex(RuntimeError, "only schedule KEEP or SCALE"):
            schedule_whop_bounty_settlement_feedback(
                opportunities=Mock(),
                jobs=Mock(),
                feedback=_feedback(directive),
                scheduled_at="2026-08-26T19:00:00Z",
            )


if __name__ == "__main__":
    unittest.main()
