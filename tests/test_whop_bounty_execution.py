import io
import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import URLError

from workflow_os.adapters.whop_bounty_execution import (
    execute_reserved_whop_bounty_submission,
    reserve_whop_bounty_submission,
)
from workflow_os.adapters.whop_bounty_http_transport import WhopBountyHttpTransport
from workflow_os.adapters.whop_bounty_submission import (
    WhopBountyDeliverable,
    WhopBountySubmissionEvidence,
)
from workflow_os.credentials import CredentialLease, CredentialRef
from workflow_os.side_effects import SideEffectLedger


class _Response:
    def __init__(self, status, body):
        self._status = status
        self._body = io.BytesIO(body)

    def getcode(self):
        return self._status

    def read(self, size=-1):
        return self._body.read(size)

    def close(self):
        pass


class _Opener:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = 0

    def open(self, request, timeout):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.response


class _CredentialProvider:
    def __init__(self, value="top-secret-whop-user-token"):
        self.value = value
        self.refs = []

    def lease(self, ref):
        self.refs.append(ref)
        return CredentialLease(self.value)


class WhopBountyExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "side-effects.sqlite"
        self.ledger = SideEffectLedger(self.db_path)
        self.evidence = WhopBountySubmissionEvidence(
            user_credential_verified=True,
            worker_identity_verified=True,
            rights_verified=True,
            campaign_requirements_verified=True,
            deliverable_verified=True,
        )
        self.deliverable = WhopBountyDeliverable(
            deliverable_type="content_url",
            urls=("https://example.com/work/123",),
            caption="Verified work",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _reserve(self, *, deliverable=None, key="whop-job-12345678"):
        return reserve_whop_bounty_submission(
            bounty_id="bnty_example123",
            deliverable=deliverable or self.deliverable,
            evidence=self.evidence,
            idempotency_key=key,
            ledger=self.ledger,
        )

    def _transport(self, *, error=None):
        response = _Response(
            201,
            json.dumps(
                {
                    "id": "btys_submission123",
                    "bounty_id": "bnty_example123",
                    "status": "submitted",
                }
            ).encode(),
        )
        opener = _Opener(response=response, error=error)
        return WhopBountyHttpTransport(opener=opener), opener

    def test_confirmed_submission_marks_side_effect_succeeded(self):
        reservation = self._reserve()
        transport, opener = self._transport()
        provider = _CredentialProvider()

        record = execute_reserved_whop_bounty_submission(
            reservation,
            ledger=self.ledger,
            credential_ref=CredentialRef(
                platform="whop", account_id="worker-1", secret_name="user_token"
            ),
            credential_provider=provider,
            transport=transport,
        )

        self.assertEqual(record.state, "SUCCEEDED")
        self.assertEqual(record.external_reference, "btys_submission123")
        self.assertEqual(record.attempt_count, 1)
        self.assertEqual(opener.calls, 1)

    def test_reservation_is_idempotent_but_payload_drift_fails_closed(self):
        first = self._reserve()
        replay = self._reserve()
        self.assertEqual(first.side_effect.request_fingerprint, replay.side_effect.request_fingerprint)

        changed = WhopBountyDeliverable(
            deliverable_type="content_url",
            urls=("https://example.com/work/changed",),
            caption="Verified work",
        )
        with self.assertRaises(ValueError):
            self._reserve(deliverable=changed)

    def test_post_reservation_deliverable_mutation_is_rejected_before_network(self):
        reservation = self._reserve()
        mutated = WhopBountyDeliverable(
            deliverable_type="content_url",
            urls=("https://example.com/work/mutated",),
            caption="Verified work",
        )
        object.__setattr__(reservation, "deliverable", mutated)
        transport, opener = self._transport()

        with self.assertRaises(ValueError):
            execute_reserved_whop_bounty_submission(
                reservation,
                ledger=self.ledger,
                credential_ref=CredentialRef(
                    platform="whop", account_id="worker-1", secret_name="user_token"
                ),
                credential_provider=_CredentialProvider(),
                transport=transport,
            )

        record = self.ledger.get(reservation.idempotency_key)
        self.assertEqual(record.state, "RESERVED")
        self.assertEqual(record.attempt_count, 0)
        self.assertEqual(opener.calls, 0)

    def test_network_error_after_execution_start_becomes_unknown(self):
        reservation = self._reserve()
        transport, _ = self._transport(error=URLError("connection lost"))

        with self.assertRaises(Exception):
            execute_reserved_whop_bounty_submission(
                reservation,
                ledger=self.ledger,
                credential_ref=CredentialRef(
                    platform="whop", account_id="worker-1", secret_name="user_token"
                ),
                credential_provider=_CredentialProvider(),
                transport=transport,
            )

        record = self.ledger.get(reservation.idempotency_key)
        self.assertIsNotNone(record)
        self.assertEqual(record.state, "UNKNOWN")
        self.assertEqual(record.attempt_count, 1)

    def test_wrong_credential_is_rejected_before_attempt_begins(self):
        reservation = self._reserve()
        transport, opener = self._transport()

        with self.assertRaises(ValueError):
            execute_reserved_whop_bounty_submission(
                reservation,
                ledger=self.ledger,
                credential_ref=CredentialRef(
                    platform="tiktok", account_id="worker-1", secret_name="access_token"
                ),
                credential_provider=_CredentialProvider(),
                transport=transport,
            )

        record = self.ledger.get(reservation.idempotency_key)
        self.assertEqual(record.state, "RESERVED")
        self.assertEqual(record.attempt_count, 0)
        self.assertEqual(opener.calls, 0)

    def test_secret_is_not_persisted_in_side_effect_database(self):
        reservation = self._reserve()
        secret = "top-secret-whop-user-token"
        transport, _ = self._transport()
        execute_reserved_whop_bounty_submission(
            reservation,
            ledger=self.ledger,
            credential_ref=CredentialRef(
                platform="whop", account_id="worker-1", secret_name="user_token"
            ),
            credential_provider=_CredentialProvider(secret),
            transport=transport,
        )

        raw = self.db_path.read_bytes()
        self.assertNotIn(secret.encode(), raw)
        self.assertNotIn(b"workflow-os-validation-placeholder", raw)

    def test_incomplete_evidence_never_reserves_side_effect(self):
        bad_evidence = WhopBountySubmissionEvidence(
            user_credential_verified=True,
            worker_identity_verified=True,
            rights_verified=False,
            campaign_requirements_verified=True,
            deliverable_verified=True,
        )
        with self.assertRaises(ValueError):
            reserve_whop_bounty_submission(
                bounty_id="bnty_example123",
                deliverable=self.deliverable,
                evidence=bad_evidence,
                idempotency_key="whop-job-12345678",
                ledger=self.ledger,
            )
        self.assertIsNone(self.ledger.get("whop-job-12345678"))


if __name__ == "__main__":
    unittest.main()
