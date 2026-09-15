from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from workflow_os.adapters.whop_bounty_http_transport import WhopBountyHttpTransport
from workflow_os.credentials import CredentialLease, CredentialRef
from workflow_os.durable_whop_bounty_binding import DurableWhopBountyBindingLedger
from workflow_os.job_queue import JobQueue
from workflow_os.openshorts_output_provenance import OpenShortsClipOutput, OpenShortsOutputProvenanceStore
from workflow_os.openshorts_output_qc import OpenShortsOutputQCEvidence
from workflow_os.side_effects import SideEffectLedger
from workflow_os.submit_reward_openshorts_whop_worker import run_submit_reward_openshorts_whop_once
from workflow_os.whop_bounty_submission_provenance import WhopBountySubmissionProvenanceLedger

NOW = "2026-09-15T04:00:00+00:00"


class _Response:
    def __init__(self):
        self.status = 201
        self.body = io.BytesIO(json.dumps({"id": "btys_worker1", "bounty_id": "bnty_worker1", "status": "submitted"}).encode())
    def getcode(self): return self.status
    def read(self, size=-1): return self.body.read(size)
    def close(self): return None


class _Opener:
    def __init__(self): self.requests = []
    def open(self, request, timeout):
        self.requests.append((request, timeout))
        return _Response()


class _Credentials:
    def lease(self, _ref): return CredentialLease("whop-worker-secret")


def _sha(payload):
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


class SubmitRewardOpenShortsWhopWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.root = root
        self.db = str(root / "state.sqlite")
        self.queue = JobQueue(self.db)
        self.effects = SideEffectLedger(self.db)
        self.outputs = OpenShortsOutputProvenanceStore(self.db)
        self.bindings = DurableWhopBountyBindingLedger(self.db)
        self.provenance = WhopBountySubmissionProvenanceLedger(self.db)
        self.key = "openshorts:7:" + "a" * 64
        self.output = OpenShortsClipOutput(
            idempotency_key=self.key,
            provider_job_id="provider-worker-1",
            clip_index=0,
            video_url="https://cdn.example.com/clip.mp4",
            download_url="https://cdn.example.com/clip.mp4?download=1",
            title="verified worker clip",
            evidence_sha256="d" * 64,
        )
        self.outputs.record_many((self.output,))
        self.opportunity = {
            "opportunity_id": "opp-worker-1",
            "source_platform": "whop_bounties",
            "campaign_id": "bnty_worker1",
            "bounty_type": "workforce",
            "machine_submission_verified": True,
            "zero_touch_execution_enabled": True,
            "rights_verification_state": "VERIFIED",
            "account_authorized": True,
            "worker_identity_verified": True,
            "campaign_requirements_verified": True,
            "deliverable_requirements_verified": True,
            "disclosure_satisfied": True,
        }

    def tearDown(self): self.tmp.cleanup()

    def _job(self, job_id):
        with sqlite3.connect(self.db) as db:
            row = db.execute(
                "SELECT state, attempt_count FROM jobs WHERE job_id=?",
                (job_id,),
            ).fetchone()
        if row is None:
            raise AssertionError(f"missing durable job {job_id}")
        return row

    def _enqueue(self, *, disclosure=True, job_type="submit_reward"):
        opportunity = dict(self.opportunity)
        opportunity["disclosure_satisfied"] = disclosure
        payload = {
            "opportunity_id": opportunity["opportunity_id"],
            "batch_fingerprint": "b" * 64,
            "opportunity_snapshot": opportunity,
            "opportunity_snapshot_sha256": _sha(opportunity),
            "revenue_control": {"opportunity_id": opportunity["opportunity_id"], "may_schedule": True},
            "batch_slot": 1,
            "upstream_render": {
                "source_job_id": 7,
                "source_request_fingerprint": "c" * 64,
                "openshorts_idempotency_key": self.key,
                "provider_job_id": self.output.provider_job_id,
                "clip_index": 0,
                "evidence_sha256": self.output.evidence_sha256,
                "video_url": self.output.video_url,
            },
        }
        return self.queue.enqueue(
            idempotency_key=f"worker-{job_type}-{disclosure}",
            opportunity_id=opportunity["opportunity_id"],
            job_type=job_type,
            payload=payload,
            available_at=NOW,
            max_attempts=3,
        )

    def _qc(self, output, **_kwargs):
        return OpenShortsOutputQCEvidence(
            idempotency_key=output.idempotency_key,
            provider_job_id=output.provider_job_id,
            clip_index=output.clip_index,
            provider_evidence_sha256=output.evidence_sha256,
            media_sha256="e" * 64,
            media_type="video/mp4",
            size_bytes=1234,
            duration_ms=15000,
            width=1080,
            height=1920,
            video_codec="h264",
            has_audio=True,
        )

    def _run(self, opener, **kwargs):
        values = dict(
            queue=self.queue,
            side_effect_ledger=self.effects,
            output_store=self.outputs,
            binding_ledger=self.bindings,
            provenance_ledger=self.provenance,
            credential_ref=CredentialRef(platform="whop", account_id="worker-account", secret_name="user_token"),
            credential_provider=_Credentials(),
            transport=WhopBountyHttpTransport(opener=opener, timeout_seconds=10),
            worker_id="submit-worker",
            now=NOW,
            workspace_root=self.root,
            allowed_download_hosts=("cdn.example.com",),
            credential_authority_verified=True,
            qc_verifier=self._qc,
        )
        values.update(kwargs)
        return run_submit_reward_openshorts_whop_once(**values)

    def test_executes_one_qc_bound_child_to_durable_success(self):
        child = self._enqueue()
        opener = _Opener()
        result = self._run(opener)
        self.assertTrue(result.attempted)
        self.assertEqual(result.execution.execution.job.state, "SUCCEEDED")
        self.assertEqual(result.execution.execution.side_effect.state, "SUCCEEDED")
        self.assertEqual(result.execution.prepared.openshorts_provider_job_id, "provider-worker-1")
        self.assertEqual(len(opener.requests), 1)
        self.assertEqual(self._job(child.job_id)[0], "SUCCEEDED")

    def test_skips_incompatible_job_without_consuming_attempt(self):
        other = self._enqueue(job_type="produce_and_publish")
        result = self._run(_Opener())
        self.assertFalse(result.attempted)
        state, attempt_count = self._job(other.job_id)
        self.assertEqual(state, "READY")
        self.assertEqual(attempt_count, 0)

    def test_missing_disclosure_fails_before_whop_io_and_requeues(self):
        child = self._enqueue(disclosure=False)
        opener = _Opener()
        with self.assertRaises(ValueError):
            self._run(opener)
        state, attempt_count = self._job(child.job_id)
        self.assertEqual(state, "FAILED_RETRYABLE")
        self.assertEqual(attempt_count, 1)
        self.assertEqual(opener.requests, [])

    def test_missing_runtime_credential_authority_claims_nothing(self):
        child = self._enqueue()
        with self.assertRaises(ValueError):
            self._run(_Opener(), credential_authority_verified=False)
        state, attempt_count = self._job(child.job_id)
        self.assertEqual(state, "READY")
        self.assertEqual(attempt_count, 0)


if __name__ == "__main__":
    unittest.main()
