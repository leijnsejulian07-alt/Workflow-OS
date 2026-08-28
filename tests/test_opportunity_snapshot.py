import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workflow_os.sqlite_lifecycle import managed_connection
from workflow_os.durable_scheduler import enqueue_controlled_candidates
from workflow_os.job_queue import JobQueue
from workflow_os.ledger import OpportunityLedger
from workflow_os.opportunity_snapshot import snapshot_opportunity, verify_opportunity_snapshot


class OpportunitySnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "workflow-os.sqlite3"
        self.ledger = OpportunityLedger(self.db_path)
        self.queue = JobQueue(self.db_path)
        self.normalized = {
            "opportunity_id": "op-1",
            "source_platform": "cliparmy",
            "campaign_id": "campaign-1",
            "discovered_at": "2026-08-22T12:00:00+00:00",
            "title": "Authorized clipping campaign",
        }
        canonical = json.dumps(self.normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        with managed_connection(sqlite3.connect(self.db_path)) as db:
            db.execute(
                "INSERT INTO opportunities(opportunity_id,normalized_json,source_platform,campaign_id,discovered_at,updated_at) VALUES(?,?,?,?,?,?)",
                (
                    "op-1",
                    canonical,
                    "cliparmy",
                    "campaign-1",
                    "2026-08-22T12:00:00+00:00",
                    "2026-08-22T12:00:00+00:00",
                ),
            )

    def tearDown(self):
        self.tmp.cleanup()

    def test_snapshot_round_trips_and_verifies(self):
        snapshot = snapshot_opportunity(self.ledger, "op-1")
        recovered = verify_opportunity_snapshot(snapshot.payload, snapshot.sha256, "op-1")
        self.assertEqual(recovered, self.normalized)
        self.assertIsNot(recovered, snapshot.payload)

    def test_missing_or_mismatched_opportunity_fails_closed(self):
        with self.assertRaises(KeyError):
            snapshot_opportunity(self.ledger, "missing")
        snapshot = snapshot_opportunity(self.ledger, "op-1")
        mutated = dict(snapshot.payload)
        mutated["title"] = "changed"
        with self.assertRaises(ValueError):
            verify_opportunity_snapshot(mutated, snapshot.sha256, "op-1")
        with self.assertRaises(ValueError):
            verify_opportunity_snapshot(snapshot.payload, snapshot.sha256, "op-2")

    def test_enqueued_snapshot_survives_restart_with_digest(self):
        snapshot = snapshot_opportunity(self.ledger, "op-1")
        candidate = {
            "opportunity_id": "op-1",
            "decision": "ACCEPT",
            "eligible_for_queue": True,
            "opportunity_snapshot": snapshot.payload,
            "opportunity_snapshot_sha256": snapshot.sha256,
            "revenue_control": {
                "opportunity_id": "op-1",
                "action": "KEEP",
                "may_schedule": True,
                "max_new_jobs": 1,
                "reasons": ["REALIZED_PROFIT_POSITIVE"],
                "realized_cash_eur": 20.0,
                "reconciled_cost_eur": 5.0,
                "realized_profit_eur": 15.0,
                "sample_count": 1,
                "policy_version": "reconciled-scaling-control/2",
            },
        }
        job = enqueue_controlled_candidates(
            self.queue,
            [candidate],
            scheduled_at="2026-08-22T12:00:00+00:00",
        )[0]
        lease = self.queue.claim(
            worker_id="worker-1",
            now="2026-08-22T12:00:01+00:00",
            lease_seconds=300,
        )
        self.assertEqual(lease.job_id, job.job_id)
        payload = self.queue.read_leased_payload(
            job.job_id,
            worker_id="worker-1",
            now="2026-08-22T12:00:02+00:00",
        )
        recovered = verify_opportunity_snapshot(
            payload["opportunity_snapshot"],
            payload["opportunity_snapshot_sha256"],
            payload["opportunity_id"],
        )
        self.assertEqual(recovered, self.normalized)

    def test_enqueue_rejects_snapshot_digest_or_identity_drift(self):
        snapshot = snapshot_opportunity(self.ledger, "op-1")
        base = {
            "opportunity_id": "op-1",
            "decision": "ACCEPT",
            "eligible_for_queue": True,
            "revenue_control": {
                "opportunity_id": "op-1",
                "action": "KEEP",
                "may_schedule": True,
                "max_new_jobs": 1,
                "realized_cash_eur": 20.0,
                "reconciled_cost_eur": 5.0,
                "realized_profit_eur": 15.0,
                "sample_count": 1,
                "policy_version": "reconciled-scaling-control/2",
            },
        }
        bad_digest = dict(base)
        bad_digest["opportunity_snapshot"] = snapshot.payload
        bad_digest["opportunity_snapshot_sha256"] = "0" * 64
        with self.assertRaises(RuntimeError):
            enqueue_controlled_candidates(
                self.queue, [bad_digest], scheduled_at="2026-08-22T12:00:00+00:00"
            )

        bad_identity = dict(base)
        bad_identity["opportunity_snapshot"] = dict(snapshot.payload, opportunity_id="other")
        bad_identity["opportunity_snapshot_sha256"] = snapshot.sha256
        with self.assertRaises(RuntimeError):
            enqueue_controlled_candidates(
                self.queue, [bad_identity], scheduled_at="2026-08-22T12:00:00+00:00"
            )


if __name__ == "__main__":
    unittest.main()
