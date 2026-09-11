import json
import unittest
from decimal import Decimal
from urllib.request import Request

from workflow_os.alpaca_paper_order_outcome import fetch_paper_order_outcome
from workflow_os.alpaca_paper_transport import AlpacaPaperCredentials, _HttpResult


class AlpacaPaperOrderOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.credentials = AlpacaPaperCredentials("paper-key", "paper-secret")

    def _payload(self, **overrides):
        payload = {
            "id": "order-123",
            "client_order_id": "client-123",
            "symbol": "AAPL",
            "side": "buy",
            "type": "market",
            "time_in_force": "day",
            "qty": "0.01",
            "filled_qty": "0.01",
            "filled_avg_price": "250.50",
            "submitted_at": "2026-09-11T08:30:00Z",
            "filled_at": "2026-09-11T08:30:01Z",
            "status": "filled",
        }
        payload.update(overrides)
        return payload

    def _request_fn(self, payload=None, *, status=200, content_type="application/json"):
        body = json.dumps(self._payload() if payload is None else payload).encode("utf-8")

        def request_fn(request: Request, timeout_seconds: float):
            self.assertEqual(request.method, "GET")
            self.assertEqual(
                request.full_url,
                "https://paper-api.alpaca.markets/v2/orders:by_client_order_id?client_order_id=client-123",
            )
            self.assertEqual(request.headers["Apca-api-key-id"], "paper-key")
            self.assertEqual(request.headers["Apca-api-secret-key"], "paper-secret")
            self.assertEqual(timeout_seconds, 10.0)
            return _HttpResult(status, body, "req-123", content_type)

        return request_fn

    def _fetch(self, request_fn):
        return fetch_paper_order_outcome(
            credentials=self.credentials,
            client_order_id="client-123",
            expected_symbol="AAPL",
            expected_qty="0.01",
            request_fn=request_fn,
        )

    def test_filled_order_returns_bound_terminal_fill_snapshot(self):
        outcome = self._fetch(self._request_fn())
        self.assertIsNotNone(outcome)
        assert outcome is not None
        self.assertEqual(outcome.external_order_id, "order-123")
        self.assertEqual(outcome.status, "filled")
        self.assertTrue(outcome.terminal)
        self.assertTrue(outcome.has_fill)
        self.assertEqual(outcome.ordered_qty, Decimal("0.01"))
        self.assertEqual(outcome.filled_qty, Decimal("0.01"))
        self.assertEqual(outcome.filled_avg_price, Decimal("250.50"))
        self.assertEqual(outcome.filled_notional_usd, Decimal("2.5050"))

    def test_open_order_is_returned_but_never_marked_terminal(self):
        payload = self._payload(
            status="new",
            filled_qty="0",
            filled_avg_price=None,
            filled_at=None,
        )
        outcome = self._fetch(self._request_fn(payload))
        self.assertIsNotNone(outcome)
        assert outcome is not None
        self.assertFalse(outcome.terminal)
        self.assertFalse(outcome.has_fill)
        self.assertIsNone(outcome.filled_notional_usd)

    def test_terminal_cancel_preserves_partial_fill_evidence(self):
        payload = self._payload(
            status="canceled",
            filled_qty="0.004",
            filled_avg_price="251.25",
        )
        outcome = self._fetch(self._request_fn(payload))
        self.assertIsNotNone(outcome)
        assert outcome is not None
        self.assertTrue(outcome.terminal)
        self.assertTrue(outcome.has_fill)
        self.assertEqual(outcome.filled_qty, Decimal("0.004"))
        self.assertEqual(outcome.filled_notional_usd, Decimal("1.00500"))

    def test_identity_mismatch_fails_closed(self):
        for field, value in (
            ("client_order_id", "other-client"),
            ("symbol", "MSFT"),
            ("side", "sell"),
            ("qty", "0.02"),
            ("type", "limit"),
            ("time_in_force", "gtc"),
        ):
            with self.subTest(field=field):
                self.assertIsNone(self._fetch(self._request_fn(self._payload(**{field: value}))))

    def test_unknown_status_fails_closed(self):
        self.assertIsNone(self._fetch(self._request_fn(self._payload(status="future_status"))))

    def test_malformed_fill_evidence_fails_closed(self):
        bad_payloads = (
            self._payload(filled_qty="0.02"),
            self._payload(filled_qty="0.01", filled_avg_price=None),
            self._payload(filled_qty="0", filled_avg_price="250.50", filled_at=None),
            self._payload(status="filled", filled_qty="0.005"),
            self._payload(filled_at="2026-09-11T08:29:59Z"),
            self._payload(filled_qty="NaN"),
            self._payload(filled_avg_price="Infinity"),
        )
        for payload in bad_payloads:
            with self.subTest(payload=payload):
                self.assertIsNone(self._fetch(self._request_fn(payload)))

    def test_http_mime_json_and_transport_failures_return_none(self):
        self.assertIsNone(self._fetch(self._request_fn(status=429)))
        self.assertIsNone(self._fetch(self._request_fn(content_type="text/html")))

        def malformed_json(request, timeout_seconds):
            return _HttpResult(200, b"{", "req-123", "application/json")

        def timeout(request, timeout_seconds):
            raise TimeoutError("network ambiguity")

        self.assertIsNone(self._fetch(malformed_json))
        self.assertIsNone(self._fetch(timeout))

    def test_live_host_is_unreachable(self):
        with self.assertRaisesRegex(ValueError, "paper API"):
            fetch_paper_order_outcome(
                credentials=self.credentials,
                client_order_id="client-123",
                expected_symbol="AAPL",
                expected_qty="0.01",
                base_url="https://api.alpaca.markets",
                request_fn=self._request_fn(),
            )


if __name__ == "__main__":
    unittest.main()
