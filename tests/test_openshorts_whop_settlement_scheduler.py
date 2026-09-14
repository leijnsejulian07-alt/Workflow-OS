from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from workflow_os.openshorts_whop_settlement_scheduler import (
    reconcile_and_schedule_prepared_openshorts_whop_payout,
)


class OpenShortsWhopSettlementSchedulerBridgeTests(unittest.TestCase):
    def _prepared(self, opportunity_id: str = "opp-open-schedule-1"):
        return SimpleNamespace(submission=SimpleNamespace(opportunity_id=opportunity_id))

    def _feedback(self, opportunity_id: str = "opp-open-schedule-1"):
        return SimpleNamespace(
            payout=SimpleNamespace(
                provenance=SimpleNamespace(opportunity_id=opportunity_id),
                reconciled_event=SimpleNamespace(opportunity_id=opportunity_id),
            ),
            scaling=SimpleNamespace(opportunity_id=opportunity_id),
        )

    @mock.patch("workflow_os.openshorts_whop_settlement_scheduler.schedule_whop_bounty_settlement_feedback")
    @mock.patch("workflow_os.openshorts_whop_settlement_scheduler.reconcile_prepared_openshorts_whop_payout_and_decide_next_action")
    def test_exact_reconciled_feedback_is_passed_to_durable_scheduler(self, reconcile, schedule):
        prepared = self._prepared()
        feedback = self._feedback()
        settlement = SimpleNamespace(settlement=feedback)
        scheduling = SimpleNamespace(feedback=feedback, jobs=(SimpleNamespace(job_id=7),))
        reconcile.return_value = settlement
        schedule.return_value = scheduling

        result = reconcile_and_schedule_prepared_openshorts_whop_payout(
            prepared,
            audit_ledger=mock.sentinel.audit,
            provenance_ledger=mock.sentinel.provenance,
            reconciliation_ledger=mock.sentinel.reconciliation,
            opportunities=mock.sentinel.opportunities,
            jobs=mock.sentinel.jobs,
            evidence=mock.sentinel.evidence,
            settlement_evidence_sha256="a" * 64,
            scheduled_at="2026-09-14T04:00:00+00:00",
            keep_jobs=2,
            scale_jobs=4,
        )

        self.assertIs(settlement, result.settlement)
        self.assertIs(scheduling, result.scheduling)
        reconcile.assert_called_once_with(
            prepared,
            audit_ledger=mock.sentinel.audit,
            provenance_ledger=mock.sentinel.provenance,
            reconciliation_ledger=mock.sentinel.reconciliation,
            evidence=mock.sentinel.evidence,
            settlement_evidence_sha256="a" * 64,
            experiment_jobs=1,
            keep_jobs=2,
            scale_jobs=4,
            min_samples_to_scale=3,
            min_realized_profit_to_scale_eur=25.0,
        )
        schedule.assert_called_once_with(
            opportunities=mock.sentinel.opportunities,
            jobs=mock.sentinel.jobs,
            feedback=feedback,
            scheduled_at="2026-09-14T04:00:00+00:00",
            job_type="produce_and_publish",
            max_attempts=3,
        )

    @mock.patch("workflow_os.openshorts_whop_settlement_scheduler.schedule_whop_bounty_settlement_feedback")
    @mock.patch("workflow_os.openshorts_whop_settlement_scheduler.reconcile_prepared_openshorts_whop_payout_and_decide_next_action")
    def test_opportunity_identity_drift_fails_before_scheduling(self, reconcile, schedule):
        prepared = self._prepared()
        feedback = self._feedback()
        feedback.scaling.opportunity_id = "opp-other"
        reconcile.return_value = SimpleNamespace(settlement=feedback)

        with self.assertRaisesRegex(RuntimeError, "scaling directive identity mismatch"):
            reconcile_and_schedule_prepared_openshorts_whop_payout(
                prepared,
                audit_ledger=mock.sentinel.audit,
                provenance_ledger=mock.sentinel.provenance,
                reconciliation_ledger=mock.sentinel.reconciliation,
                opportunities=mock.sentinel.opportunities,
                jobs=mock.sentinel.jobs,
                evidence=mock.sentinel.evidence,
                settlement_evidence_sha256="b" * 64,
                scheduled_at="2026-09-14T04:00:00+00:00",
            )

        schedule.assert_not_called()

    @mock.patch("workflow_os.openshorts_whop_settlement_scheduler.schedule_whop_bounty_settlement_feedback")
    @mock.patch("workflow_os.openshorts_whop_settlement_scheduler.reconcile_prepared_openshorts_whop_payout_and_decide_next_action")
    def test_scheduler_feedback_drift_fails_closed(self, reconcile, schedule):
        prepared = self._prepared()
        feedback = self._feedback()
        reconcile.return_value = SimpleNamespace(settlement=feedback)
        schedule.return_value = SimpleNamespace(feedback=self._feedback("opp-other"), jobs=())

        with self.assertRaisesRegex(RuntimeError, "feedback drifted"):
            reconcile_and_schedule_prepared_openshorts_whop_payout(
                prepared,
                audit_ledger=mock.sentinel.audit,
                provenance_ledger=mock.sentinel.provenance,
                reconciliation_ledger=mock.sentinel.reconciliation,
                opportunities=mock.sentinel.opportunities,
                jobs=mock.sentinel.jobs,
                evidence=mock.sentinel.evidence,
                settlement_evidence_sha256="c" * 64,
                scheduled_at="2026-09-14T04:00:00+00:00",
            )


if __name__ == "__main__":
    unittest.main()
