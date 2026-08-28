from __future__ import annotations

import hashlib
import json
import unittest
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from workflow_os.adapters.awin_transaction_http_transport import (
    AwinTransactionHttpTransport,
    AwinTransactionTransportError,
    build_awin_transaction_url,
)


class _FakeResponse:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self._body = body
        self._status = status
        self.closed = False

    def read(self, limit: int = -1) -> bytes:
        if limit < 0:
            return self._body
        return self._body[:limit]

    def getcode(self) -> int:
        return self._status

    def close(self) -> None:
        self.closed = True


class _FakeOpener:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.requests = []
        self.timeouts = []

    def open(self, request, timeout):  # noqa: ANN001
        self.requests.append(request)
        self.timeouts.append(timeout)
        return self.response


class AwinTransactionHttpTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start = datetime(2026, 8, 1, tzinfo=timezone.utc)
        self.end = datetime(2026, 8, 2, tzinfo=timezone.utc)

    def test_build_url_uses_exact_https_origin_and_bounded_query(self) -> None:
        url, start, end, date_type, status, advertiser = build_awin_transaction_url(
            publisher_id=12345,
            start_at=self.start,
            end_at=self.end,
            status="approved",
            advertiser_id=67890,
        )
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.hostname, "api.awin.com")
        self.assertEqual(parsed.path, "/publishers/12345/transactions/")
        self.assertEqual(query["timezone"], ["UTC"])
        self.assertEqual(query["showBasketProducts"], ["false"])
        self.assertEqual(query["status"], ["approved"])
        self.assertEqual(query["advertiserId"], ["67890"])
        self.assertNotIn("accessToken", query)
        self.assertEqual(start, "2026-08-01T00:00:00Z")
        self.assertEqual(end, "2026-08-02T00:00:00Z")
        self.assertEqual(date_type, "transaction")
        self.assertEqual(status, "approved")
        self.assertEqual(advertiser, 67890)

    def test_rejects_query_windows_over_31_days(self) -> None:
        with self.assertRaisesRegex(ValueError, "at most 31 days"):
            build_awin_transaction_url(
                publisher_id=12345,
                start_at=self.start,
                end_at=self.start + timedelta(days=31, seconds=1),
            )

    def test_rejects_naive_timestamps_and_invalid_filters(self) -> None:
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            build_awin_transaction_url(
                publisher_id=12345,
                start_at=datetime(2026, 8, 1),
                end_at=self.end,
            )
        with self.assertRaisesRegex(ValueError, "date_type"):
            build_awin_transaction_url(
                publisher_id=12345,
                start_at=self.start,
                end_at=self.end,
                date_type="created",
            )
        with self.assertRaisesRegex(ValueError, "status"):
            build_awin_transaction_url(
                publisher_id=12345,
                start_at=self.start,
                end_at=self.end,
                status="paid",
            )

    def test_fetch_uses_bearer_header_and_returns_raw_evidence_digest(self) -> None:
        payload = [
            {
                "id": 999,
                "status": "approved",
                "clickRef": "workflow-os:awin-demo",
            }
        ]
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        response = _FakeResponse(body)
        opener = _FakeOpener(response)
        transport = AwinTransactionHttpTransport(opener=opener, timeout_seconds=7)

        result = transport.fetch(
            access_token="super-secret-token",
            publisher_id=12345,
            start_at=self.start,
            end_at=self.end,
            status="approved",
        )

        self.assertEqual(len(opener.requests), 1)
        request = opener.requests[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("Authorization"), "Bearer super-secret-token")
        self.assertNotIn("super-secret-token", request.full_url)
        self.assertEqual(opener.timeouts, [7.0])
        self.assertTrue(response.closed)
        self.assertEqual(result.publisher_id, 12345)
        self.assertEqual(result.status, "approved")
        self.assertEqual(result.transactions, tuple(payload))
        self.assertEqual(result.evidence_sha256, hashlib.sha256(body).hexdigest())

    def test_fetch_rejects_malformed_or_non_list_json(self) -> None:
        for body in (b"not-json", b'{"transactions":[]}'):
            with self.subTest(body=body):
                transport = AwinTransactionHttpTransport(
                    opener=_FakeOpener(_FakeResponse(body))
                )
                with self.assertRaises(AwinTransactionTransportError):
                    transport.fetch(
                        access_token="token",
                        publisher_id=12345,
                        start_at=self.start,
                        end_at=self.end,
                    )

    def test_fetch_rejects_non_object_transaction_items(self) -> None:
        body = json.dumps([{"id": 1}, "hostile"]).encode("utf-8")
        transport = AwinTransactionHttpTransport(opener=_FakeOpener(_FakeResponse(body)))
        with self.assertRaisesRegex(AwinTransactionTransportError, "non-object"):
            transport.fetch(
                access_token="token",
                publisher_id=12345,
                start_at=self.start,
                end_at=self.end,
            )

    def test_fetch_rejects_oversized_response(self) -> None:
        body = b"[" + (b" " * (2 * 1024 * 1024)) + b"]"
        transport = AwinTransactionHttpTransport(opener=_FakeOpener(_FakeResponse(body)))
        with self.assertRaisesRegex(AwinTransactionTransportError, "size limit"):
            transport.fetch(
                access_token="token",
                publisher_id=12345,
                start_at=self.start,
                end_at=self.end,
            )

    def test_fetch_rejects_non_200_without_leaking_token(self) -> None:
        transport = AwinTransactionHttpTransport(
            opener=_FakeOpener(_FakeResponse(b'{"error":"no"}', status=503))
        )
        with self.assertRaisesRegex(AwinTransactionTransportError, "HTTP 503") as ctx:
            transport.fetch(
                access_token="do-not-leak-this",
                publisher_id=12345,
                start_at=self.start,
                end_at=self.end,
            )
        self.assertNotIn("do-not-leak-this", str(ctx.exception))

    def test_rejects_hostile_credentials_and_timeout_values(self) -> None:
        transport = AwinTransactionHttpTransport(opener=_FakeOpener(_FakeResponse(b"[]")))
        with self.assertRaisesRegex(ValueError, "access token"):
            transport.fetch(
                access_token="bad\r\ntoken",
                publisher_id=12345,
                start_at=self.start,
                end_at=self.end,
            )
        for value in (0, 121, float("inf"), True):
            with self.subTest(value=value):
                with self.assertRaises((TypeError, ValueError)):
                    AwinTransactionHttpTransport(timeout_seconds=value)


if __name__ == "__main__":
    unittest.main()
