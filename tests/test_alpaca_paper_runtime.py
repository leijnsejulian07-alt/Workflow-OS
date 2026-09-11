import json
import tempfile
import unittest
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


class AlpacaPaperRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = SideEffectLedger(Path(self.tmp.name) / "effects.db")
        self.credentials = AlpacaPaperCredentials("paper-key", "paper-secret")
        self.policy = AlpacaPaperStrategyPolicy(strategy_id="minute-body-v1")

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
            order_request_fn=order_ok,
        )
        self.assertEqual(first.status, "EXECUTED")
        self.assertEqual(first.side_effect.state, "SUCCEEDED")
        self.assertEqual(calls, ["POST"])

        second = run_alpaca_paper_once(
            credentials=self.credentials,
            account_id="paper-account",
            symbol="AAPL",
            ledger=self.ledger,
            policy=self.policy,
            market_request_fn=market_ok,
            order_request_fn=order_ok,
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
            order_request_fn=order_ambiguous_then_found,
        )
        self.assertEqual(first.status, "EXECUTED")
        self.assertEqual(first.side_effect.state, "UNKNOWN")

        second = run_alpaca_paper_once(
            credentials=self.credentials,
            account_id="paper-account",
            symbol="AAPL",
            ledger=self.ledger,
            policy=self.policy,
            market_request_fn=market_ok,
            order_request_fn=order_ambiguous_then_found,
        )
        self.assertEqual(second.status, "RECONCILED")
        self.assertEqual(second.side_effect.state, "SUCCEEDED")
        self.assertEqual(calls, ["POST", "GET"])

    def test_bearish_bar_holds_without_order_transport(self):
        def market_bearish(request, timeout):
            body = {"bar": {"t": "2026-09-11T00:00:00Z", "o": 100.0, "h": 100.1, "l": 99.0, "c": 99.5, "v": 1000, "n": 10, "vw": 99.7}}
            return _HttpResult(200, json.dumps(body).encode(), "market-rid", "application/json")

        def forbidden_order(request, timeout):
            raise AssertionError("order transport must not be called")

        result = run_alpaca_paper_once(
            credentials=self.credentials,
            account_id="paper-account",
            symbol="AAPL",
            ledger=self.ledger,
            policy=self.policy,
            market_request_fn=market_bearish,
            order_request_fn=forbidden_order,
        )
        self.assertEqual(result.status, "HOLD")
        self.assertEqual(result.decision.reason, "NO_LONG_SIGNAL")

    def test_notional_limit_holds_fail_closed(self):
        policy = AlpacaPaperStrategyPolicy(
            strategy_id="minute-body-v1", quantity_shares=1.0, maximum_order_notional_usd=25.0
        )

        def forbidden_order(request, timeout):
            raise AssertionError("order transport must not be called")

        result = run_alpaca_paper_once(
            credentials=self.credentials,
            account_id="paper-account",
            symbol="AAPL",
            ledger=self.ledger,
            policy=policy,
            market_request_fn=market_ok,
            order_request_fn=forbidden_order,
        )
        self.assertEqual(result.status, "HOLD")
        self.assertEqual(result.decision.reason, "ORDER_NOTIONAL_RISK_LIMIT")


if __name__ == "__main__":
    unittest.main()
