import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from workflow_os.alpaca_paper_runtime import AlpacaPaperStrategyPolicy, run_alpaca_paper_once
from workflow_os.alpaca_paper_transport import AlpacaPaperCredentials, _HttpResult
from workflow_os.side_effects import SideEffectLedger


def market_ok(request, timeout):
    body = {
        "bar": {
            "t": "2026-09-11T00:00:00Z",
            "o": 100.0,
            "h": 101.0,
            "l": 99.9,
            "c": 100.2,
            "v": 1000,
            "n": 10,
            "vw": 100.1,
        }
    }
    return _HttpResult(200, json.dumps(body).encode(), "market-rid", "application/json")


def clock_ok(request, timeout):
    body = {"timestamp": "2026-09-11T00:01:00Z", "is_open": True}
    return _HttpResult(200, json.dumps(body).encode(), "clock-rid", "application/json")


def account_ok(request, timeout):
    body = {
        "id": "paper-account",
        "status": "ACTIVE",
        "currency": "USD",
        "buying_power": "1000.00",
        "trading_blocked": False,
        "account_blocked": False,
        "trade_suspended_by_user": False,
    }
    return _HttpResult(200, json.dumps(body).encode(), "account-rid", "application/json")


class AlpacaPaperRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = SideEffectLedger(Path(self.tmp.name) / "effects.db")
        self.credentials = AlpacaPaperCredentials("paper-key", "paper-secret")
        self.policy = AlpacaPaperStrategyPolicy(strategy_id="minute-body-v1")
        self.now_utc = datetime(2026, 9, 11, 0, 1, tzinfo=timezone.utc)

    def tearDown(self):
        self.tmp.cleanup()

    def test_real_observation_can_drive_one_idempotent_paper_order(self):
        calls = []

        def order_ok(request, timeout):
            calls.append(request.get_method())
            payload = json.loads(request.data.decode())
            return _HttpResult(
                200,
                json.dumps({"id": "paper-order-1", "client_order_id": payload["client_order_id"]}).encode(),
                "order-rid",
                "application/json",
            )

        first = run_alpaca_paper_once(
            credentials=self.credentials,
            account_id="paper-account",
            symbol="AAPL",
            ledger=self.ledger,
            policy=self.policy,
            market_request_fn=market_ok,
            clock_request_fn=clock_ok,
            account_request_fn=account_ok,
            order_request_fn=order_ok,
            now_utc=self.now_utc,
        )
        self.assertEqual(first.status, "EXECUTED")
        self.assertEqual(first.side_effect.state, "SUCCEEDED")
        self.assertEqual(calls, ["POST"])

        def forbidden_gate(request, timeout):
            raise AssertionError("already-succeeded replay must not re-run new-order gates")

        second = run_alpaca_paper_once(
            credentials=self.credentials,
            account_id="paper-account",
            symbol="AAPL",
            ledger=self.ledger,
            policy=self.policy,
            market_request_fn=market_ok,
            clock_request_fn=forbidden_gate,
            account_request_fn=forbidden_gate,
            order_request_fn=order_ok,
            now_utc=self.now_utc,
        )
        self.assertEqual(second.status, "ALREADY_SUCCEEDED")
        self.assertEqual(calls, ["POST"])

    def test_ambiguous_post_reconciles_without_duplicate_post(self):
        calls = []

        def order_ambiguous_then_found(request, timeout):
            calls.append(request.get_method())
            if request.get_method() == "POST":
                return _HttpResult(500, b"{}", "post-rid", "application/json")
            query = request.full_url.split("client_order_id=", 1)[1]
            return _HttpResult(
                200,
                json.dumps({"id": "paper-order-2", "client_order_id": query}).encode(),
                "lookup-rid",
                "application/json",
            )

        first = run_alpaca_paper_once(
            credentials=self.credentials,
            account_id="paper-account",
            symbol="AAPL",
            ledger=self.ledger,
            policy=self.policy,
            market_request_fn=market_ok,
            clock_request_fn=clock_ok,
            account_request_fn=account_ok,
            order_request_fn=order_ambiguous_then_found,
            now_utc=self.now_utc,
        )
        self.assertEqual(first.status, "EXECUTED")
        self.assertEqual(first.side_effect.state, "UNKNOWN")

        def forbidden_gate(request, timeout):
            raise AssertionError("UNKNOWN reconciliation must remain read-only and bypass new-order gates")

        second = run_alpaca_paper_once(
            credentials=self.credentials,
            account_id="paper-account",
            symbol="AAPL",
            ledger=self.ledger,
            policy=self.policy,
            market_request_fn=market_ok,
            clock_request_fn=forbidden_gate,
            account_request_fn=forbidden_gate,
            order_request_fn=order_ambiguous_then_found,
            now_utc=self.now_utc,
        )
        self.assertEqual(second.status, "RECONCILED")
        self.assertEqual(second.side_effect.state, "SUCCEEDED")
        self.assertEqual(calls, ["POST", "GET"])

    def test_bearish_bar_holds_without_order_transport(self):
        def market_bearish(request, timeout):
            body = {"bar": {"t": "2026-09-11T00:00:00Z", "o": 100.0, "h": 100.1, "l": 99.0, "c": 99.5, "v": 1000, "n": 10, "vw": 99.7}}
            return _HttpResult(200, json.dumps(body).encode(), "market-rid", "application/json")

        def forbidden(request, timeout):
            raise AssertionError("clock/account/order transport must not be called")

        result = run_alpaca_paper_once(
            credentials=self.credentials,
            account_id="paper-account",
            symbol="AAPL",
            ledger=self.ledger,
            policy=self.policy,
            market_request_fn=market_bearish,
            clock_request_fn=forbidden,
            account_request_fn=forbidden,
            order_request_fn=forbidden,
            now_utc=self.now_utc,
        )
        self.assertEqual(result.status, "HOLD")
        self.assertEqual(result.decision.reason, "NO_LONG_SIGNAL")

    def test_notional_limit_holds_fail_closed(self):
        policy = AlpacaPaperStrategyPolicy(
            strategy_id="minute-body-v1", quantity_shares=1.0, maximum_order_notional_usd=25.0
        )

        def forbidden(request, timeout):
            raise AssertionError("clock/account/order transport must not be called")

        result = run_alpaca_paper_once(
            credentials=self.credentials,
            account_id="paper-account",
            symbol="AAPL",
            ledger=self.ledger,
            policy=policy,
            market_request_fn=market_ok,
            clock_request_fn=forbidden,
            account_request_fn=forbidden,
            order_request_fn=forbidden,
            now_utc=self.now_utc,
        )
        self.assertEqual(result.status, "HOLD")
        self.assertEqual(result.decision.reason, "ORDER_NOTIONAL_RISK_LIMIT")

    def test_stale_observation_holds_before_order_transport(self):
        def forbidden(request, timeout):
            raise AssertionError("clock/account/order transport must not be called for stale market data")

        result = run_alpaca_paper_once(
            credentials=self.credentials,
            account_id="paper-account",
            symbol="AAPL",
            ledger=self.ledger,
            policy=self.policy,
            market_request_fn=market_ok,
            clock_request_fn=forbidden,
            account_request_fn=forbidden,
            order_request_fn=forbidden,
            now_utc=datetime(2026, 9, 11, 0, 3, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(result.status, "HOLD")
        self.assertEqual(result.decision.reason, "STALE_MARKET_OBSERVATION")
        self.assertIsNone(result.side_effect)

    def test_future_observation_holds_before_order_transport(self):
        def market_future(request, timeout):
            body = {
                "bar": {
                    "t": "2026-09-11T00:02:00Z",
                    "o": 100.0,
                    "h": 101.0,
                    "l": 99.9,
                    "c": 100.2,
                    "v": 1000,
                    "n": 10,
                    "vw": 100.1,
                }
            }
            return _HttpResult(200, json.dumps(body).encode(), "market-rid", "application/json")

        def forbidden(request, timeout):
            raise AssertionError("clock/account/order transport must not be called for future market data")

        result = run_alpaca_paper_once(
            credentials=self.credentials,
            account_id="paper-account",
            symbol="AAPL",
            ledger=self.ledger,
            policy=self.policy,
            market_request_fn=market_future,
            clock_request_fn=forbidden,
            account_request_fn=forbidden,
            order_request_fn=forbidden,
            now_utc=self.now_utc,
        )
        self.assertEqual(result.status, "HOLD")
        self.assertEqual(result.decision.reason, "FUTURE_MARKET_OBSERVATION")
        self.assertIsNone(result.side_effect)


if __name__ == "__main__":
    unittest.main()
