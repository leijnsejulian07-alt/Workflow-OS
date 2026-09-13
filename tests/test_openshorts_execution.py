from __future__ import annotations

import hashlib
import hmac
import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import URLError

from workflow_os.adapters.openshorts_hosted import OpenShortsHostedTransport, OpenShortsHostedTransportError
from workflow_os.durable_worker import VerifiedLeasedOpportunityJob
from workflow_os.job_queue import JobRecord
from workflow_os.openshorts_execution import (
    OpenShortsExecutionEvidenceStore,
    dispatch_prepared_openshorts,
    reconcile_terminal_status,
    record_terminal_webhook,
)
from workflow_os.openshorts_job_preparation import prepare_durable_openshorts_processing
from workflow_os.side_effects import SideEffectLedger


class FakeResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status, self.body = status, body
    def getcode(self): return self.status
    def read(self, size=-1): return self.body if size < 0 else self.body[:size]
    def close(self): pass

class QueueOpener:
    def __init__(self, *responses) -> None:
        self.responses = list(responses)
    def open(self, request, timeout):
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def verified_job() -> VerifiedLeasedOpportunityJob:
    opportunity = {
        "opportunity_id": "opp-1", "rights_verification_state": "VERIFIED",
        "usage_rights": "licensed campaign assets", "expected_owner_minutes": 0.0,
        "expected_net_profit": 12.5,
    }
    record = JobRecord(7, "job-key", "opp-1", "produce_and_publish", "a" * 64,
                       "LEASED", 1, 3, "2026-09-13T00:00:00+00:00", None, "worker", None)
    return VerifiedLeasedOpportunityJob(record, {}, opportunity)


class OpenShortsExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.ledger = SideEffectLedger(root / "side.sqlite")
        self.evidence = OpenShortsExecutionEvidenceStore(root / "evidence.sqlite")
        self.prepared = prepare_durable_openshorts_processing(
            verified_job(), source_url="https://youtu.be/abc",
            webhook_url="https://hooks.example.com/openshorts",
            credential_authority_verified=True, cost_authority_verified=True,
            ledger=self.ledger,
        )
        self.key = self.prepared.reservation.idempotency_key
        self.api_key = "osk_1234567890abcdef"
        self.secret = "s" * 32

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def dispatch(self, opener=None):
        opener = opener or QueueOpener(FakeResponse(202, b'{"job_id":"job-123"}'))
        return dispatch_prepared_openshorts(
            self.prepared, ledger=self.ledger,
            transport=OpenShortsHostedTransport(opener=opener),
            api_key=self.api_key, webhook_secret=self.secret,
        )

    def test_dispatch_binds_provider_job_to_side_effect(self) -> None:
        result = self.dispatch()
        current = self.ledger.get(self.key)
        self.assertEqual(result.provider_job_id, "job-123")
        self.assertEqual(current.state, "SUCCEEDED")
        self.assertEqual(current.external_reference, "job-123")
        with self.assertRaisesRegex(RuntimeError, "already durably bound"):
            self.dispatch()

    def test_ambiguous_transport_failure_becomes_unknown(self) -> None:
        with self.assertRaises(OpenShortsHostedTransportError):
            self.dispatch(QueueOpener(URLError("connection reset")))
        self.assertEqual(self.ledger.get(self.key).state, "UNKNOWN")
        with self.assertRaisesRegex(RuntimeError, "not retry-authorized"):
            self.dispatch()

    def test_local_validation_failure_is_definitely_not_applied(self) -> None:
        bad_ledger = SideEffectLedger(Path(self.tmp.name) / "bad.sqlite")
        bad = prepare_durable_openshorts_processing(
            verified_job(), source_url="https://example.com/not-allowlisted",
            webhook_url="https://hooks.example.com/openshorts",
            credential_authority_verified=True, cost_authority_verified=True,
            ledger=bad_ledger,
        )
        with self.assertRaises(ValueError):
            dispatch_prepared_openshorts(
                bad, ledger=bad_ledger,
                transport=OpenShortsHostedTransport(opener=QueueOpener()),
                api_key=self.api_key, webhook_secret=self.secret,
            )
        self.assertEqual(bad_ledger.get(bad.reservation.idempotency_key).state, "FAILED_RETRYABLE")

    def test_signed_terminal_webhook_records_immutable_evidence(self) -> None:
        self.dispatch()
        body = b'{"event":"job.completed","job_id":"job-123","clips":[]}'
        signature = hmac.new(self.secret.encode(), body, hashlib.sha256).hexdigest()
        evidence = record_terminal_webhook(
            ledger=self.ledger, evidence_store=self.evidence, idempotency_key=self.key,
            body=body, signature_header=f"sha256={signature}", webhook_secret=self.secret,
        )
        self.assertEqual(evidence.terminal_state, "COMPLETED")
        replay = record_terminal_webhook(
            ledger=self.ledger, evidence_store=self.evidence, idempotency_key=self.key,
            body=body, signature_header=f"sha256={signature}", webhook_secret=self.secret,
        )
        self.assertEqual(replay, evidence)

    def test_webhook_job_mismatch_fails_closed(self) -> None:
        self.dispatch()
        body = b'{"event":"job.failed","job_id":"other-job"}'
        signature = hmac.new(self.secret.encode(), body, hashlib.sha256).hexdigest()
        with self.assertRaisesRegex(RuntimeError, "not bound"):
            record_terminal_webhook(
                ledger=self.ledger, evidence_store=self.evidence, idempotency_key=self.key,
                body=body, signature_header=f"sha256={signature}", webhook_secret=self.secret,
            )
        self.assertIsNone(self.evidence.get(self.key))

    def test_status_reconciliation_waits_for_nonterminal_job(self) -> None:
        self.dispatch()
        transport = OpenShortsHostedTransport(
            opener=QueueOpener(FakeResponse(200, b'{"status":"processing"}'))
        )
        result = reconcile_terminal_status(
            ledger=self.ledger, evidence_store=self.evidence,
            idempotency_key=self.key, transport=transport, api_key=self.api_key,
        )
        self.assertIsNone(result)
        self.assertIsNone(self.evidence.get(self.key))

    def test_status_reconciliation_records_terminal_evidence(self) -> None:
        self.dispatch()
        payload = {"status": "failed", "job_id": "job-123", "reason": "provider failure"}
        transport = OpenShortsHostedTransport(
            opener=QueueOpener(FakeResponse(200, json.dumps(payload).encode()))
        )
        evidence = reconcile_terminal_status(
            ledger=self.ledger, evidence_store=self.evidence,
            idempotency_key=self.key, transport=transport, api_key=self.api_key,
        )
        self.assertEqual(evidence.terminal_state, "FAILED")
        self.assertEqual(evidence.source, "status_api")

    def test_status_reconciliation_rejects_provider_job_mismatch(self) -> None:
        self.dispatch()
        transport = OpenShortsHostedTransport(
            opener=QueueOpener(FakeResponse(200, b'{"status":"completed","job_id":"other-job"}'))
        )
        with self.assertRaisesRegex(OpenShortsHostedTransportError, "does not match durable binding"):
            reconcile_terminal_status(
                ledger=self.ledger, evidence_store=self.evidence,
                idempotency_key=self.key, transport=transport, api_key=self.api_key,
            )
        self.assertIsNone(self.evidence.get(self.key))

    def test_unknown_status_fails_closed(self) -> None:
        self.dispatch()
        transport = OpenShortsHostedTransport(
            opener=QueueOpener(FakeResponse(200, b'{"status":"mystery"}'))
        )
        with self.assertRaises(OpenShortsHostedTransportError):
            reconcile_terminal_status(
                ledger=self.ledger, evidence_store=self.evidence,
                idempotency_key=self.key, transport=transport, api_key=self.api_key,
            )


if __name__ == "__main__":
    unittest.main()
