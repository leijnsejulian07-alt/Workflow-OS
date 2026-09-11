import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from workflow_os.alpaca_paper_runtime import AlpacaPaperStrategyPolicy, run_alpaca_paper_once
from workflow_os.alpaca_paper_transport import AlpacaPaperCredentials, _HttpResult
from workflow_os.side_effects import SideEffectLedger


def market_ok(request, timeout):
    body = {"bar": {"t": "2026-09-11T00:00:00Z", "o": 100.0, "h": 101.0, "l": 99.9, "c": 100.2, "v": 1000, "n": 10, "vw": 100.1}}
    return _HttpResult(200, json.dumps(body).encode(), "market-rid", "application/json")


def clock_ok(request, timeout):
    body = {"timestamp": "2026-09-11T00:01:00Z", "is_open": True}
    return _HttpResult(200, json.dumps(body).encode(), "clock-rid", "application/json")


def account_result(*, buying_power="1000.00", trading_blocked=False):
    body = {
        "id": "paper-account",
        "status": "ACTIVE",
        "currency": "USD",
        "buying_power": buying_power,
        "trading_blocked": trading_blocked,
        "account_blocked": False,
        "trade_suspended_by_user": False,
    }
    return _HttpResult(200, json.dumps(body).encode(), "account-rid", "application/json")


class AlpacaPaperRuntimeAccountGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = SideEffectLedger(Path(self.tmp.name) / "effects.db")
        self.credentials = AlpacaPaperCredentials("paper-key", "paper-secret")
        self.policy = AlpacaPaperStrategyPolicy(strategy_id="minute-body-v1")
        self.now_utc = datetime(2026, 9, 11, 0, 1, tzinfo=timezone.utc)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, account_request_fn):
        def forbidden_order(request, timeout):
            raise AssertionError("paper order transport must not be called")

        return run_alpaca_paper_once(
            credentials=self.credentials,
            account_id="paper-account",
            symbol="AAPL",
            ledger=self.ledger,
            policy=self.policy,
            market_request_fn=market_ok,
            clock_request_fn=clock_ok,
            account_request_fn=account_request_fn,
            order_request_fn=forbidden_order,
            now_utc=self.now_utc,
        )

    def test_account_transport_failure_blocks_new_order_without_reservation(self):
        result = self._run(lambda request, timeout: _HttpResult(503, b"{}", "rid", "application/json"))
        self.assertEqual(result.status, "ACCOUNT_UNAVAILABLE")
        self.assertEqual(result.decision.action, "BUY")
        self.assertIsNone(result.side_effect)

    def test_blocked_account_blocks_new_order_without_reservation(self):
        result = self._run(lambda request, timeout: account_result(trading_blocked=True))
        self.assertEqual(result.status, "ACCOUNT_NOT_TRADABLE")
        self.assertIsNone(result.side_effect)

    def test_insufficient_buying_power_blocks_new_order_without_reservation(self):
        result = self._run(lambda request, timeout: account_result(buying_power="0.50"))
        self.assertEqual(result.status, "INSUFFICIENT_BUYING_POWER")
        self.assertIsNone(result.side_effect)


if __name__ == "__main__":
    unittest.main()
