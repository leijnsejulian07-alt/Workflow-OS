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


NOW = "2026-08-24T08:30:00+00:00"


class _Response:
    def __init__(self, status, body):
        self._status = status
        self._body = io.BytesIO(body)

    def getcode(self):
        return self._status

    def read(self, size=-1):
        return self._body.read(size)

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
    def __init__(self, value="whop-user-secret", *, error=None):
        self.value = value
        self.error = error
        self.refs = []

    def lease(self, ref):
        self.refs.append(ref)
        if self.error is not None:
            raise self.error
        return CredentialLease(self.value)


class WhopBountyEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.queue = JobQueue(root / "jobs.sqlite")
        self.effects = SideEffectLedger(root / "effects.sqlite")
        self.bindings = DurableWhopBountyBindingLedger(root / "bindings.sqlite")
        payload = {"opportunity_id": "opp-whop-1", "campaign_id": "bnty_example123"}
        self.queue.enqueue(
            idempotency_key="job-whop-e2e-1",
            opportunity_id="opp-whop-1",
            job_type="produce_and_publish",
            payload=payload,
            available_at=NOW,
            max_attempts=3,
        )
        leased = self.queue.claim(worker_id="worker-1", now=NOW, lease_seconds=300)
        self.assertIsNotNone(leased)
        opportunity = {
            "opportunity_id": "opp-whop-1",
            "source_platform": "whop_bounties",
            "campaign_id": "bnty_example123",
            "bounty_type": "workforce",
            "machine_submission_verified": True,
            "zero_touch_execution_enabled": True,
            "rights_verification_state": "VERIFIED",
            "account_authorized": True,
            "worker_identity_verified": True,
            "campaign_requirements_verified": True,
            "deliverable_requirements_verified": True,
        }
        self.job = VerifiedLeasedOpportunityJob(
            job=leased,
            payload=payload,
            opportunity=opportunity,
        )
        self.deliverable = WhopBountyDeliverable(
            deliverable_type="content_url",
            urls=("https://example.com/work/123",),
            caption="verified deliverable",
        )
        self.ref = CredentialRef(platform="whop", account_id="worker-1", secret_name="user_token")

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *, opener, provider=None, credential_authority_verified=True, deliverable_verified=True):
        return execute_verified_whop_bounty_job(
            self.job,
            self.deliverable,
            credential_authority_verified=credential_authority_verified,
            deliverable_verified=deliverable_verified,
            queue=self.queue,
            worker_id="worker-1",
            now=NOW,
            binding_ledger=self.bindings,
            side_effect_ledger=self.effects,
            credential_ref=self.ref,
            credential_provider=provider or _CredentialProvider(),
            transport=WhopBountyHttpTransport(opener=opener, timeout_seconds=10),
        )

    def test_confirmed_submission_closes_full_durable_loop(self):
        opener = _Opener(
            response=_Response(
                201,
                json.dumps(
                    {
                        "id": "btys_submission123",
                        "bounty_id": "bnty_example123",
                        "status": "submitted",
                    }
                ).encode(),
            )
        )
        provider = _CredentialProvider()

        result = self._run(opener=opener, provider=provider)

        self.assertEqual(result.execution.side_effect.state, "SUCCEEDED")
        self.assertEqual(result.execution.job.state, "SUCCEEDED")
        self.assertEqual(result.execution.side_effect.external_reference, "btys_submission123")
        self.assertEqual(result.prepared.job_id, result.execution.binding.job_id)
        self.assertEqual(result.prepared.opportunity_id, result.execution.binding.opportunity_id)
        self.assertEqual(len(opener.requests), 1)
        self.assertEqual(provider.refs, [self.ref])

    def test_ambiguous_network_failure_never_becomes_blind_retry(self):
        result = self._run(opener=_Opener(error=URLError("offline")))
        self.assertEqual(result.execution.side_effect.state, "UNKNOWN")
        self.assertEqual(result.execution.job.state, "UNKNOWN")

    def test_credential_provider_failure_before_dispatch_is_retry_safe(self):
        provider = _CredentialProvider(error=RuntimeError("vault unavailable"))
        opener = _Opener(response=_Response(201, b"{}"))
        result = self._run(opener=opener, provider=provider)
        self.assertEqual(result.execution.side_effect.state, "RESERVED")
        self.assertEqual(result.execution.job.state, "FAILED_RETRYABLE")
        self.assertEqual(opener.requests, [])

    def test_unverified_authority_stops_before_reservation_or_network(self):
        opener = _Opener(response=_Response(201, b"{}"))
        with self.assertRaises(ValueError):
            self._run(opener=opener, credential_authority_verified=False)
        self.assertEqual(opener.requests, [])
        self.assertIsNone(self.bindings.get(self.job.job.job_id))

    def test_wrong_credential_type_stops_before_reservation(self):
        self.ref = CredentialRef(platform="whop", account_id="worker-1", secret_name="api_key")
        opener = _Opener(response=_Response(201, b"{}"))
        with self.assertRaises(ValueError):
            self._run(opener=opener)
        self.assertEqual(opener.requests, [])
        self.assertIsNone(self.bindings.get(self.job.job.job_id))


if __name__ == "__main__":
    unittest.main()
