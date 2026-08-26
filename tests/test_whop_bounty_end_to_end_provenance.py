from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import URLError

from workflow_os.adapters.whop_bounty_http_transport import WhopBountyHttpTransport
from workflow_os.adapters.whop_bounty_submission import WhopBountyDeliverable
from workflow_os.credentials import CredentialLease, CredentialRef
from workflow_os.durable_whop_bounty_binding import DurableWhopBountyBindingLedger
from workflow_os.durable_worker import VerifiedLeasedOpportunityJob
from workflow_os.job_queue import JobQueue
from workflow_os.side_effects import SideEffectLedger
from workflow_os.whop_bounty_end_to_end import execute_verified_whop_bounty_job
from workflow_os.whop_bounty_submission_provenance import WhopBountySubmissionProvenanceLedger

NOW = "2026-08-26T15:00:00+00:00"


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


class WhopBountyEndToEndProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.queue = JobQueue(root / "jobs.sqlite")
        self.effects = SideEffectLedger(root / "effects.sqlite")
        self.bindings = DurableWhopBountyBindingLedger(root / "bindings.sqlite")
        self.provenance = WhopBountySubmissionProvenanceLedger(root / "provenance.sqlite")
        payload = {"opportunity_id": "opp-whop-prov-1", "campaign_id": "bnty_prov123"}
        self.queue.enqueue(
            idempotency_key="job-whop-prov-1",
            opportunity_id="opp-whop-prov-1",
            job_type="produce_and_publish",
            payload=payload,
            available_at=NOW,
            max_attempts=3,
        )
        leased = self.queue.claim(worker_id="worker-prov-1", now=NOW, lease_seconds=300)
        self.assertIsNotNone(leased)
        self.job = VerifiedLeasedOpportunityJob(
            job=leased,
            payload=payload,
            opportunity={
                "opportunity_id": "opp-whop-prov-1",
                "source_platform": "whop_bounties",
                "campaign_id": "bnty_prov123",
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
        self.deliverable = WhopBountyDeliverable(
            deliverable_type="content_url",
            urls=("https://example.com/work/prov-1",),
            caption="verified deliverable",
        )
        self.ref = CredentialRef(platform="whop", account_id="worker-prov-1", secret_name="user_token")

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, opener):
        return execute_verified_whop_bounty_job(
            self.job,
            self.deliverable,
            credential_authority_verified=True,
            deliverable_verified=True,
            queue=self.queue,
            worker_id="worker-prov-1",
            now=NOW,
            binding_ledger=self.bindings,
            side_effect_ledger=self.effects,
            credential_ref=self.ref,
            credential_provider=_CredentialProvider(),
            transport=WhopBountyHttpTransport(opener=opener, timeout_seconds=10),
            provenance_ledger=self.provenance,
        )

    def test_confirmed_submission_records_provenance_in_same_end_to_end_run(self):
        opener = _Opener(
            response=_Response(
                201,
                json.dumps({
                    "id": "btys_prov123",
                    "bounty_id": "bnty_prov123",
                    "status": "submitted",
                }).encode(),
            )
        )

        result = self._run(opener)

        self.assertEqual("SUCCEEDED", result.execution.job.state)
        self.assertEqual("SUCCEEDED", result.execution.side_effect.state)
        self.assertIsNotNone(result.provenance)
        self.assertEqual("opp-whop-prov-1", result.provenance.opportunity_id)
        self.assertEqual("bnty_prov123", result.provenance.bounty_id)
        self.assertEqual("btys_prov123", result.provenance.external_submission_reference)
        self.assertEqual(result.provenance, self.provenance.get_by_reference("btys_prov123"))
        self.assertEqual(1, len(opener.requests))

    def test_ambiguous_network_result_does_not_create_provenance(self):
        result = self._run(_Opener(error=URLError("offline")))

        self.assertEqual("UNKNOWN", result.execution.job.state)
        self.assertEqual("UNKNOWN", result.execution.side_effect.state)
        self.assertIsNone(result.provenance)
        self.assertIsNone(self.provenance.get_by_reference("btys_prov123"))


if __name__ == "__main__":
    unittest.main()
