from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from workflow_os.job_queue import JobQueue
from workflow_os.openshorts_output_provenance import OpenShortsClipOutput
from workflow_os.openshorts_whop_enqueue import enqueue_completed_openshorts_whop_jobs


NOW = "2026-09-14T20:30:00+00:00"


class OpenShortsWhopEnqueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tempdir.name) / "workflow.sqlite3")
        self.queue = JobQueue(self.db_path)
        self.source = self.queue.enqueue(
            idempotency_key="render-source",
            opportunity_id="opp-1",
            job_type="produce_and_publish",
            payload={
                "opportunity_id": "opp-1",
                "batch_fingerprint": "a" * 64,
                "opportunity_snapshot": {"opportunity_id": "opp-1"},
                "opportunity_snapshot_sha256": "b" * 64,
                "revenue_control": {"opportunity_id": "opp-1", "may_schedule": True},
                "batch_slot": 1,
            },
            available_at=NOW,
        )
        leased = self.queue.claim(worker_id="render-worker", now=NOW, allowed_job_types={"produce_and_publish"})
        assert leased is not None
        self.source = self.queue.complete(leased.job_id, worker_id="render-worker", now=NOW)
        digest = hashlib.sha256(
            f"openshorts-job\n{self.source.job_id}\n{self.source.request_fingerprint}".encode("utf-8")
        ).hexdigest()
        self.openshorts_key = f"openshorts:{self.source.job_id}:{digest}"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _output(self, *, index: int = 0) -> OpenShortsClipOutput:
        return OpenShortsClipOutput(
            idempotency_key=self.openshorts_key,
            provider_job_id="provider-job-1",
            clip_index=index,
            video_url=f"https://api.openshorts.app/api/files/provider-job-1/clip-{index}.mp4",
            download_url=f"https://api.openshorts.app/api/files/provider-job-1/clip-{index}.mp4?download=1",
            title=f"Clip {index}",
            evidence_sha256="c" * 64,
        )

    def test_completed_output_creates_separate_submit_reward_job(self) -> None:
        created = enqueue_completed_openshorts_whop_jobs(
            state_db_path=self.db_path,
            openshorts_idempotency_key=self.openshorts_key,
            outputs=(self._output(),),
            available_at=NOW,
        )

        self.assertEqual(len(created), 1)
        child = created[0]
        self.assertNotEqual(child.job_id, self.source.job_id)
        self.assertEqual(child.job_type, "submit_reward")
        self.assertEqual(child.opportunity_id, self.source.opportunity_id)
        self.assertEqual(child.state, "READY")

        leased = self.queue.claim(worker_id="whop-worker", now=NOW, allowed_job_types={"submit_reward"})
        self.assertIsNotNone(leased)
        assert leased is not None
        payload = self.queue.read_leased_payload(leased.job_id, worker_id="whop-worker", now=NOW)
        upstream = payload["upstream_render"]
        self.assertEqual(upstream["source_job_id"], self.source.job_id)
        self.assertEqual(upstream["source_request_fingerprint"], self.source.request_fingerprint)
        self.assertEqual(upstream["openshorts_idempotency_key"], self.openshorts_key)
        self.assertEqual(upstream["provider_job_id"], "provider-job-1")
        self.assertEqual(upstream["clip_index"], 0)
        self.assertEqual(upstream["evidence_sha256"], "c" * 64)
        self.assertEqual(payload["revenue_control"]["may_schedule"], True)

    def test_replay_is_idempotent_and_does_not_duplicate_child_job(self) -> None:
        first = enqueue_completed_openshorts_whop_jobs(
            state_db_path=self.db_path,
            openshorts_idempotency_key=self.openshorts_key,
            outputs=(self._output(),),
            available_at=NOW,
        )
        second = enqueue_completed_openshorts_whop_jobs(
            state_db_path=self.db_path,
            openshorts_idempotency_key=self.openshorts_key,
            outputs=(self._output(),),
            available_at=NOW,
        )
        self.assertEqual(first, second)

    def test_each_clip_gets_its_own_durable_submission_job(self) -> None:
        created = enqueue_completed_openshorts_whop_jobs(
            state_db_path=self.db_path,
            openshorts_idempotency_key=self.openshorts_key,
            outputs=(self._output(index=0), self._output(index=1)),
            available_at=NOW,
        )
        self.assertEqual(len(created), 2)
        self.assertNotEqual(created[0].idempotency_key, created[1].idempotency_key)

    def test_forged_parent_key_fails_before_child_enqueue(self) -> None:
        forged = f"openshorts:{self.source.job_id}:" + "0" * 64
        forged_output = OpenShortsClipOutput(
            idempotency_key=forged,
            provider_job_id="provider-job-1",
            clip_index=0,
            video_url="https://api.openshorts.app/api/files/provider-job-1/clip-0.mp4",
            download_url="https://api.openshorts.app/api/files/provider-job-1/clip-0.mp4?download=1",
            title="Clip",
            evidence_sha256="c" * 64,
        )
        with self.assertRaises(RuntimeError):
            enqueue_completed_openshorts_whop_jobs(
                state_db_path=self.db_path,
                openshorts_idempotency_key=forged,
                outputs=(forged_output,),
                available_at=NOW,
            )
        self.assertIsNone(self.queue.claim(worker_id="whop-worker", now=NOW, allowed_job_types={"submit_reward"}))

    def test_output_must_match_parent_side_effect(self) -> None:
        output = self._output()
        mismatched = OpenShortsClipOutput(
            idempotency_key=self.openshorts_key[:-1] + ("0" if self.openshorts_key[-1] != "0" else "1"),
            provider_job_id=output.provider_job_id,
            clip_index=output.clip_index,
            video_url=output.video_url,
            download_url=output.download_url,
            title=output.title,
            evidence_sha256=output.evidence_sha256,
        )
        with self.assertRaises(RuntimeError):
            enqueue_completed_openshorts_whop_jobs(
                state_db_path=self.db_path,
                openshorts_idempotency_key=self.openshorts_key,
                outputs=(mismatched,),
                available_at=NOW,
            )


if __name__ == "__main__":
    unittest.main()
