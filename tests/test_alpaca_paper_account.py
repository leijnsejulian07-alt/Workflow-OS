import json
import unittest

from workflow_os.alpaca_paper_account import fetch_paper_account_snapshot
from workflow_os.alpaca_paper_transport import AlpacaPaperCredentials, _HttpResult


class AlpacaPaperAccountTests(unittest.TestCase):
    def setUp(self):
        self.credentials = AlpacaPaperCredentials("paper-key", "paper-secret")
        self.account_id = "paper-account-id"

    def _body(self, **overrides):
        body = {
            "id": self.account_id,
            "status": "ACTIVE",
            "currency": "USD",
            "buying_power": "1000.50",
            "trading_blocked": False,
            "account_blocked": False,
            "trade_suspended_by_user": False,
        }
        body.update(overrides)
        return body

    def test_reads_exact_paper_account_and_reports_trading_enabled(self):
        seen = []

        def request_ok(request, timeout):
            seen.append((request.full_url, request.get_method(), timeout, request.headers))
            return _HttpResult(
                200,
                json.dumps(self._body()).encode(),
                "account-rid",
                "application/json",
            )

        snapshot = fetch_paper_account_snapshot(
            credentials=self.credentials,
            expected_account_id=self.account_id,
            request_fn=request_ok,
        )

        self.assertIsNotNone(snapshot)
        self.assertTrue(snapshot.trading_enabled)
        self.assertEqual(snapshot.buying_power_usd, 1000.50)
        self.assertEqual(snapshot.request_id, "account-rid")
        self.assertEqual(seen[0][0], "https://paper-api.alpaca.markets/v2/account")
        self.assertEqual(seen[0][1], "GET")
        self.assertEqual(seen[0][2], 10.0)
        self.assertEqual(seen[0][3]["Apca-api-key-id"], "paper-key")
        self.assertEqual(seen[0][3]["Apca-api-secret-key"], "paper-secret")

    def test_blocked_or_suspended_account_is_not_trading_enabled(self):
        for field in ("trading_blocked", "account_blocked", "trade_suspended_by_user"):
            with self.subTest(field=field):
                def request_blocked(request, timeout, field=field):
                    return _HttpResult(
                        200,
                        json.dumps(self._body(**{field: True})).encode(),
                        "rid",
                        "application/json",
                    )

                snapshot = fetch_paper_account_snapshot(
                    credentials=self.credentials,
                    expected_account_id=self.account_id,
                    request_fn=request_blocked,
                )
                self.assertIsNotNone(snapshot)
                self.assertFalse(snapshot.trading_enabled)

    def test_non_active_or_non_usd_account_is_not_trading_enabled(self):
        cases = ({"status": "ACCOUNT_UPDATED"}, {"currency": "EUR"})
        for overrides in cases:
            with self.subTest(overrides=overrides):
                def request_state(request, timeout, overrides=overrides):
                    return _HttpResult(
                        200,
                        json.dumps(self._body(**overrides)).encode(),
                        "rid",
                        "application/json",
                    )

                snapshot = fetch_paper_account_snapshot(
                    credentials=self.credentials,
                    expected_account_id=self.account_id,
                    request_fn=request_state,
                )
                self.assertIsNotNone(snapshot)
                self.assertFalse(snapshot.trading_enabled)

    def test_account_identity_mismatch_fails_closed(self):
        def wrong_account(request, timeout):
            return _HttpResult(
                200,
                json.dumps(self._body(id="different-account")).encode(),
                "rid",
                "application/json",
            )

        self.assertIsNone(
            fetch_paper_account_snapshot(
                credentials=self.credentials,
                expected_account_id=self.account_id,
                request_fn=wrong_account,
            )
        )

    def test_transport_http_mime_and_json_ambiguity_fail_closed(self):
        responses = (
            _HttpResult(401, b"{}", "rid", "application/json"),
            _HttpResult(429, b"{}", "rid", "application/json"),
            _HttpResult(500, b"{}", "rid", "application/json"),
            _HttpResult(200, json.dumps(self._body()).encode(), "rid", "text/html"),
            _HttpResult(200, b"not-json", "rid", "application/json"),
        )
        for response in responses:
            with self.subTest(status=response.status, content_type=response.content_type):
                self.assertIsNone(
                    fetch_paper_account_snapshot(
                        credentials=self.credentials,
                        expected_account_id=self.account_id,
                        request_fn=lambda request, timeout, response=response: response,
                    )
                )

    def test_missing_malformed_or_negative_risk_fields_fail_closed(self):
        cases = (
            {"buying_power": None},
            {"buying_power": "nan"},
            {"buying_power": "inf"},
            {"buying_power": "-1"},
            {"trading_blocked": "false"},
            {"account_blocked": 0},
            {"trade_suspended_by_user": None},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides):
                def malformed(request, timeout, overrides=overrides):
                    return _HttpResult(
                        200,
                        json.dumps(self._body(**overrides)).encode(),
                        "rid",
                        "application/json",
                    )

                self.assertIsNone(
                    fetch_paper_account_snapshot(
                        credentials=self.credentials,
                        expected_account_id=self.account_id,
                        request_fn=malformed,
                    )
                )

    def test_live_base_url_is_rejected_before_request(self):
        called = []

        def forbidden(request, timeout):
            called.append(True)
            raise AssertionError("request must not be called")

        with self.assertRaises(ValueError):
            fetch_paper_account_snapshot(
                credentials=self.credentials,
                expected_account_id=self.account_id,
                base_url="https://api.alpaca.markets",
                request_fn=forbidden,
            )
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
