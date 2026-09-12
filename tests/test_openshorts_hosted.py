from __future__ import annotations

import hashlib
import hmac
import json
import unittest
from urllib.error import URLError

from workflow_os.adapters.openshorts_hosted import (
    OpenShortsHostedTransport,
    OpenShortsHostedTransportError,
    verify_openshorts_webhook,
)


class FakeResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self._status = status
        self._body = body
        self.closed = False

    def getcode(self) -> int:
        return self._status

    def read(self, size: int = -1) -> bytes:
        return self._body if size < 0 else self._body[:size]

    def close(self) -> None:
        self.closed = True


class FakeOpener:
    def __init__(self, response: FakeResponse | Exception) -> None:
        self.response = response
        self.requests = []

    def open(self, request, timeout):  # noqa: ANN001
        self.requests.append((request, timeout))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class OpenShortsHostedTransportTests(unittest.TestCase):
    def test_process_video_uses_bearer_auth_and_bounded_contract(self) -> None:
        opener = FakeOpener(FakeResponse(202, b'{"job_id":"job-123"}'))
        transport = OpenShortsHostedTransport(opener=opener)
        result = transport.process_video(
            api_key="osk_1234567890abcdef",
            source_url="https://www.youtube.com/watch?v=abc",
            webhook_url="https://hooks.example.com/openshorts",
            webhook_secret="s" * 32,
        )
        self.assertEqual(result.job_id, "job-123")
        request, timeout = opener.requests[0]
        self.assertEqual(request.full_url, "https://api.openshorts.app/api/process")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.headers["Authorization"], "Bearer osk_1234567890abcdef")
        payload = json.loads(request.data.decode("utf-8"))
        self.assertIs(payload["acknowledged"], True)
        self.assertEqual(payload["webhook_secret"], "s" * 32)
        self.assertEqual(timeout, 30.0)

    def test_process_rejects_private_source_ip(self) -> None:
        transport = OpenShortsHostedTransport(opener=FakeOpener(FakeResponse(202, b"{}")))
        with self.assertRaises(ValueError):
            transport.process_video(
                api_key="osk_1234567890abcdef",
                source_url="https://127.0.0.1/video.mp4",
                webhook_url="https://hooks.example.com/openshorts",
                webhook_secret="s" * 32,
            )

    def test_process_rejects_nonallowlisted_source_host(self) -> None:
        transport = OpenShortsHostedTransport(opener=FakeOpener(FakeResponse(202, b"{}")))
        with self.assertRaises(ValueError):
            transport.process_video(
                api_key="osk_1234567890abcdef",
                source_url="https://metadata.google.internal/video.mp4",
                webhook_url="https://hooks.example.com/openshorts",
                webhook_secret="s" * 32,
            )

    def test_process_rejects_local_webhook(self) -> None:
        transport = OpenShortsHostedTransport(opener=FakeOpener(FakeResponse(202, b"{}")))
        with self.assertRaises(ValueError):
            transport.process_video(
                api_key="osk_1234567890abcdef",
                source_url="https://www.youtube.com/watch?v=abc",
                webhook_url="https://localhost/hook",
                webhook_secret="s" * 32,
            )

    def test_process_rejects_malformed_api_key(self) -> None:
        transport = OpenShortsHostedTransport(opener=FakeOpener(FakeResponse(202, b"{}")))
        with self.assertRaises(ValueError):
            transport.process_video(
                api_key="bad-key",
                source_url="https://www.youtube.com/watch?v=abc",
                webhook_url="https://hooks.example.com/openshorts",
                webhook_secret="s" * 32,
            )

    def test_process_rejects_malformed_job_response(self) -> None:
        transport = OpenShortsHostedTransport(opener=FakeOpener(FakeResponse(202, b'{"ok":true}')))
        with self.assertRaises(OpenShortsHostedTransportError):
            transport.process_video(
                api_key="osk_1234567890abcdef",
                source_url="https://www.youtube.com/watch?v=abc",
                webhook_url="https://hooks.example.com/openshorts",
                webhook_secret="s" * 32,
            )

    def test_get_status_escapes_job_id(self) -> None:
        opener = FakeOpener(FakeResponse(200, b'{"status":"processing"}'))
        transport = OpenShortsHostedTransport(opener=opener)
        payload = transport.get_status(api_key="osk_1234567890abcdef", job_id="job-123")
        self.assertEqual(payload["status"], "processing")
        request, _ = opener.requests[0]
        self.assertEqual(request.full_url, "https://api.openshorts.app/api/status/job-123")
        self.assertEqual(request.get_method(), "GET")

    def test_network_error_does_not_expose_secret(self) -> None:
        transport = OpenShortsHostedTransport(opener=FakeOpener(URLError("boom secret")))
        with self.assertRaisesRegex(OpenShortsHostedTransportError, "failed before a confirmed response"):
            transport.get_status(api_key="osk_1234567890abcdef", job_id="job-123")

    def test_webhook_signature_and_terminal_event_verify(self) -> None:
        body = b'{"event":"job.completed","job_id":"job-123","clips":[]}'
        secret = "x" * 32
        digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        event = verify_openshorts_webhook(
            body=body,
            signature_header=f"sha256={digest}",
            webhook_secret=secret,
        )
        self.assertEqual(event.event, "job.completed")
        self.assertEqual(event.job_id, "job-123")
        self.assertEqual(event.body_sha256, hashlib.sha256(body).hexdigest())

    def test_webhook_rejects_bad_signature(self) -> None:
        body = b'{"event":"job.completed","job_id":"job-123","clips":[]}'
        with self.assertRaises(ValueError):
            verify_openshorts_webhook(
                body=body,
                signature_header="sha256=" + "0" * 64,
                webhook_secret="x" * 32,
            )

    def test_webhook_rejects_nonterminal_event(self) -> None:
        body = b'{"event":"job.processing","job_id":"job-123"}'
        secret = "x" * 32
        digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        with self.assertRaises(OpenShortsHostedTransportError):
            verify_openshorts_webhook(
                body=body,
                signature_header=f"sha256={digest}",
                webhook_secret=secret,
            )


if __name__ == "__main__":
    unittest.main()
