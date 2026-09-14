from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

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

NOW = "2026-09-15T00:00:00+00:00"


class _Response:
    def __init__(self, body: bytes):
        self.status = 201
        self.body = io.BytesIO(body)

    def getcode(self):
        return self.status

    def read(self, size=-1):
        return self.body.read(size)

    def close(self):
        return None


class _Opener:
    def __init__(self):
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        return _Response(json.dumps({"id": "btys_child123", "bounty_id": "bnty_child123", "status": "submitted"}).encode())


class _CredentialProvider:
    def lease(self, _ref):
        return CredentialLease("whop-user-secret")


class SubmitRewardOpenShortsWhopExecutionTests(unittest.TestCase):
    def test_executes_child_job_bound_to_parent_render_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queue = JobQueue(root / "jobs.sqlite")
            effects = SideEffectLedger(root / "effects.sqlite")
            bindings = DurableWhopBountyBindingLedger(root / "bindings.sqlite")
            provenance = WhopBountySubmissionProvenanceLedger(root / "provenance.sqlite")
            parent_job_id = 77
            openshorts_key = f"openshorts:{parent_job_id}:" + "b" * 64
            payload = {
                "opportunity_id": "opp-child-1",
                "campaign_id": "bnty_child123",
                "upstream_render": {
                    "source_job_id": parent_job_id,
                    "source_request_fingerprint": "a" * 64,
                    "openshorts_idempotency_key": openshorts_key,
                    "provider_job_id": "job_parent_123",
                    "clip_index": 0,
                    "evidence_sha256": "c" * 64,
                    "video_url": "https://cdn.example.com/clip.mp4",
                },
            }
            queue.enqueue(
                idempotency_key="submit-child-1",
                opportunity_id="opp-child-1",
                job_type="submit_reward",
                payload=payload,
                available_at=NOW,
                max_attempts=3,
            )
            leased = queue.claim(
                worker_id="whop-worker-child",
                now=NOW,
                lease_seconds=300,
                allowed_job_types={"submit_reward"},
            )
            self.assertIsNotNone(leased)
            verified = VerifiedLeasedOpportunityJob(
                job=leased,
                payload=payload,
                opportunity={
                    "opportunity_id": "opp-child-1",
                    "source_platform": "whop_bounties",
                    "campaign_id": "bnty_child123",
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
            handoff = PreparedOpenShortsWhopDeliverable(
                opportunity_id="opp-child-1",
                openshorts_idempotency_key=openshorts_key,
                provider_job_id="job_parent_123",
                clip_index=0,
                evidence_sha256="c" * 64,
                deliverable=WhopBountyDeliverable(
                    deliverable_type="content_url",
                    urls=("https://cdn.example.com/clip.mp4",),
                    caption="verified child clip",
                ),
            )
            prepared = reserve_verified_openshorts_whop_submission(
                verified,
                handoff,
                credential_authority_verified=True,
                ledger=effects,
            )
            opener = _Opener()
            result = execute_prepared_openshorts_whop_submission(
                verified,
                prepared,
                queue=queue,
                worker_id="whop-worker-child",
                now=NOW,
                binding_ledger=bindings,
                side_effect_ledger=effects,
                credential_ref=CredentialRef(
                    platform="whop",
                    account_id="whop-worker-child",
                    secret_name="user_token",
                ),
                credential_provider=_CredentialProvider(),
                transport=WhopBountyHttpTransport(opener=opener, timeout_seconds=10),
                provenance_ledger=provenance,
            )

            self.assertEqual("SUCCEEDED", result.execution.job.state)
            self.assertEqual("SUCCEEDED", result.execution.side_effect.state)
            self.assertEqual("job_parent_123", result.prepared.openshorts_provider_job_id)
            self.assertIsNotNone(result.provenance)
            self.assertEqual("btys_child123", result.provenance.submission_reference)
            self.assertEqual(1, len(opener.requests))


if __name__ == "__main__":
    unittest.main()
