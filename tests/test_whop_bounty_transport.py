import io
import json
import unittest
from urllib.error import URLError

from workflow_os.adapters.whop_bounty_credentials import submit_whop_bounty_with_credential
from workflow_os.adapters.whop_bounty_http_transport import (
    WhopBountyHttpTransport,
    WhopBountyTransportError,
)
from workflow_os.adapters.whop_bounty_submission import (
    WhopBountyDeliverable,
    WhopBountySubmissionEvidence,
    build_workforce_submission_request,
)
from workflow_os.credentials import CredentialLease, CredentialRef


class _Response:
    def __init__(self, status, body):
        self._status = status
        self._body = io.BytesIO(body)
        self.closed = False

    def getcode(self):
        return self._status

    def read(self, size=-1):
        return self._body.read(size)

    def close(self):
        self.closed = True


class _Opener:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request, timeout))
        if self.error is not None:
            raise self.error
        return self.response


class _CredentialProvider:
    def __init__(self, value="whop-user-secret"):
        self.value = value
        self.refs = []

    def lease(self, ref):
        self.refs.append(ref)
        return CredentialLease(self.value)


class WhopBountyTransportTests(unittest.TestCase):
    def _evidence(self):
        return WhopBountySubmissionEvidence(
            user_credential_verified=True,
            worker_identity_verified=True,
            rights_verified=True,
            campaign_requirements_verified=True,
            deliverable_verified=True,
        )

    def _deliverable(self):
        return WhopBountyDeliverable(
            deliverable_type="content_url",
            urls=("https://example.com/work/123",),
            caption="Verified work",
        )

    def _request(self):
        return build_workforce_submission_request(
            bounty_id="bnty_example123",
            deliverable=self._deliverable(),
            evidence=self._evidence(),
            user_token="whop-user-secret",
            idempotency_key="job-12345678",
        )

    def test_submits_exact_official_request_and_parses_confirmation(self):
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
        opener = _Opener(response=response)
        transport = WhopBountyHttpTransport(opener=opener, timeout_seconds=12)

        result = transport.submit(self._request(), expected_bounty_id="bnty_example123")

        self.assertEqual(result.submission_id, "btys_submission123")
        self.assertEqual(len(opener.requests), 1)
        request, timeout = opener.requests[0]
        self.assertEqual(request.full_url, "https://api.whop.com/api/v1/bounty_submissions")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(timeout, 12.0)
        self.assertTrue(response.closed)

    def test_rejects_mutated_destination_before_network(self):
        request = self._request()
        object.__setattr__(request, "url", "https://evil.example/api/v1/bounty_submissions")
        opener = _Opener(response=_Response(201, b"{}"))
        transport = WhopBountyHttpTransport(opener=opener)

        with self.assertRaises(ValueError):
            transport.submit(request, expected_bounty_id="bnty_example123")
        self.assertEqual(opener.requests, [])

    def test_rejects_unconfirmed_response(self):
        response = _Response(200, b'{"id":"btys_submission123","bounty_id":"bnty_example123","status":"submitted"}')
        transport = WhopBountyHttpTransport(opener=_Opener(response=response))
        with self.assertRaises(WhopBountyTransportError):
            transport.submit(self._request(), expected_bounty_id="bnty_example123")

    def test_rejects_malformed_or_oversized_response(self):
        malformed = WhopBountyHttpTransport(opener=_Opener(response=_Response(201, b"not-json")))
        with self.assertRaises(WhopBountyTransportError):
            malformed.submit(self._request(), expected_bounty_id="bnty_example123")

        oversized_body = b"{" + (b"a" * (256 * 1024 + 1))
        oversized = WhopBountyHttpTransport(opener=_Opener(response=_Response(201, oversized_body)))
        with self.assertRaises(WhopBountyTransportError):
            oversized.submit(self._request(), expected_bounty_id="bnty_example123")

    def test_network_failure_is_ambiguous_transport_error(self):
        transport = WhopBountyHttpTransport(opener=_Opener(error=URLError("offline")))
        with self.assertRaises(WhopBountyTransportError):
            transport.submit(self._request(), expected_bounty_id="bnty_example123")

    def test_credential_wrapper_requires_whop_user_token(self):
        response = _Response(
            201,
            b'{"id":"btys_submission123","bounty_id":"bnty_example123","status":"submitted"}',
        )
        transport = WhopBountyHttpTransport(opener=_Opener(response=response))
        provider = _CredentialProvider()

        result = submit_whop_bounty_with_credential(
            bounty_id="bnty_example123",
            deliverable=self._deliverable(),
            evidence=self._evidence(),
            credential_ref=CredentialRef(platform="whop", account_id="worker-1", secret_name="user_token"),
            credential_provider=provider,
            idempotency_key="job-12345678",
            transport=transport,
        )
        self.assertEqual(result.status, "submitted")
        self.assertEqual(len(provider.refs), 1)

        for ref in (
            CredentialRef(platform="tiktok", account_id="worker-1", secret_name="user_token"),
            CredentialRef(platform="whop", account_id="worker-1", secret_name="api_key"),
        ):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                submit_whop_bounty_with_credential(
                    bounty_id="bnty_example123",
                    deliverable=self._deliverable(),
                    evidence=self._evidence(),
                    credential_ref=ref,
                    credential_provider=provider,
                    idempotency_key="job-12345678",
                    transport=transport,
                )

    def test_timeout_bounds_fail_closed(self):
        for timeout in (0, 121, True, "30"):
            with self.subTest(timeout=timeout), self.assertRaises((TypeError, ValueError)):
                WhopBountyHttpTransport(opener=_Opener(), timeout_seconds=timeout)


if __name__ == "__main__":
    unittest.main()
