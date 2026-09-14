from __future__ import annotations

import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from urllib.error import URLError

from workflow_os.adapters.whop_bounty_http_transport import WhopBountyHttpTransport
from workflow_os.adapters.whop_bounty_submission import WhopBountyDeliverable
from workflow_os.credentials import CredentialLease, CredentialRef
from workflow_os.durable_whop_bounty_binding import DurableWhopBountyBindingLedger
from workflow_os.durable_worker import VerifiedLeasedOpportunityJob
from workflow_os.job_queue import JobQueue
from workflow_os.openshorts_whop_execution import execute_prepared_openshorts_whop_submission
from workflow_os.openshorts_whop_handoff import PreparedOpenShortsWhopDeliverable
from workflow_os.openshorts_whop_reservation import reserve_verified_openshorts_whop_submission
from workflow_os.side_effects import SideEffectLedger
from workflow_os.whop_bounty_submission_provenance import WhopBountySubmissionProvenanceLedger

NOW = "2026-09-14T00:00:00+00:00"


class _Response:
    def __init__(self, status: int, body: bytes):
        self.status = status
        self.body = io.BytesIO(body)

    def getcode(self):
        return self.status

    def read(self, size=-1):
        return self.body.read(size)

    def close(self):
        return None


class _Opener:
    def __init__(self, *, response=None, error=None):
        self.response = response
        self.error = error
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        if self.error is not None:
            raise self.error
        return self.response


class _CredentialProvider:
    def lease(self, _ref):
        return CredentialLease("whop-user-secret")


class OpenShortsWhopExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.queue = JobQueue(root / "jobs.sqlite")
        self.effects = SideEffectLedger(root / "effects.sqlite")
        self.bindings = DurableWhopBountyBindingLedger(root / "bindings.sqlite")
        self.provenance = WhopBountySubmissionProvenanceLedger(root / "provenance.sqlite")
        payload = {"opportunity_id": "opp-open-whop-1", "campaign_id": "bnty_open123"}
        self.queue.enqueue(
            idempotency_key="job-open-whop-1",
            opportunity_id="opp-open-whop-1",
            job_type="produce_and_publish",
            payload=payload,
            available_at=NOW,
            max_attempts=3,
        )
        leased = self.queue.claim(worker_id="worker-open-1", now=NOW, lease_seconds=300)
        self.assertIsNotNone(leased)
        self.job = VerifiedLeasedOpportunityJob(
            job=leased,
            payload=payload,
            opportunity={
                "opportunity_id": "opp-open-whop-1",
                "source_platform": "whop_bounties",
                "campaign_id": "bnty_open123",
                "bounty_type": "workforce",
                "machine_submission_verified": True,
                "zero_touch_execution_enabled": True,
                "rights_verification_state": "VERIFIED",
                "account_authorized": True,
                "worker_identity_verified": True,
                "campaign_requirements_verified": True,
                "deliverable_requirements_verified": True,
            },
        )
        self.handoff = PreparedOpenShortsWhopDeliverable(
            opportunity_id="opp-open-whop-1",
            openshorts_idempotency_key=f"openshorts:{leased.job_id}:" + "b" * 64,
            provider_job_id="job_open_123",
            clip_index=0,
            evidence_sha256="c" * 64,
            deliverable=WhopBountyDeliverable(
                deliverable_type="content_url",
                urls=("https://cdn.example.com/clip.mp4",),
                caption="verified clip",
            ),
        )
        self.prepared = reserve_verified_openshorts_whop_submission(
            self.job,
            self.handoff,
            credential_authority_verified=True,
            ledger=self.effects,
        )
        self.ref = CredentialRef(platform="whop", account_id="worker-open-1", secret_name="user_token")

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, opener, *, prepared=None):
        return execute_prepared_openshorts_whop_submission(
            self.job,
            prepared or self.prepared,
            queue=self.queue,
            worker_id="worker-open-1",
            now=NOW,
            binding_ledger=self.bindings,
            side_effect_ledger=self.effects,
            credential_ref=self.ref,
            credential_provider=_CredentialProvider(),
            transport=WhopBountyHttpTransport(opener=opener, timeout_seconds=10),
            provenance_ledger=self.provenance,
        )

    def test_confirmed_execution_preserves_openshorts_binding_and_records_provenance(self):
        opener = _Opener(
            response=_Response(
                201,
                json.dumps({"id": "btys_open123", "bounty_id": "bnty_open123", "status": "submitted"}).encode(),
            )
        )
        result = self._run(opener)

        self.assertEqual("SUCCEEDED", result.execution.job.state)
        self.assertEqual("SUCCEEDED", result.execution.side_effect.state)
        self.assertEqual("job_open_123", result.prepared.openshorts_provider_job_id)
        self.assertEqual("c" * 64, result.prepared.openshorts_evidence_sha256)
        self.assertIsNotNone(result.provenance)
        self.assertEqual("btys_open123", result.provenance.submission_reference)
        self.assertEqual(1, len(opener.requests))

    def test_ambiguous_transport_does_not_create_payout_provenance(self):
        result = self._run(_Opener(error=URLError("offline")))

        self.assertEqual("UNKNOWN", result.execution.job.state)
        self.assertEqual("UNKNOWN", result.execution.side_effect.state)
        self.assertIsNone(result.provenance)

    def test_rejects_prepared_job_identity_drift_before_network_io(self):
        opener = _Opener(
            response=_Response(201, json.dumps({"id": "btys_never", "bounty_id": "bnty_open123"}).encode())
        )
        drifted = replace(
            self.prepared,
            submission=replace(self.prepared.submission, job_id=self.job.job.job_id + 1),
        )
        with self.assertRaises(RuntimeError):
            self._run(opener, prepared=drifted)
        self.assertEqual([], opener.requests)

    def test_rejects_non_reserved_side_effect_before_network_io(self):
        key = self.prepared.submission.reservation.side_effect.idempotency_key
        self.effects.begin_attempt(key)
        self.effects.mark_failed(key, definitely_not_applied=False)
        opener = _Opener(
            response=_Response(201, json.dumps({"id": "btys_never", "bounty_id": "bnty_open123"}).encode())
        )
        with self.assertRaises(RuntimeError):
            self._run(opener)
        self.assertEqual([], opener.requests)


if __name__ == "__main__":
    unittest.main()

