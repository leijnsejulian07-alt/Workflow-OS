import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from workflow_os.alpaca_paper_runtime import AlpacaPaperStrategyPolicy, run_alpaca_paper_once
from workflow_os.alpaca_paper_transport import AlpacaPaperCredentials, _HttpResult
from workflow_os.side_effects import SideEffectLedger


NOW = datetime(2026, 9, 11, 0, 1, tzinfo=timezone.utc)


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


def clock_result(timestamp, is_open=True):
    body = {"timestamp": timestamp, "is_open": is_open}
    return _HttpResult(200, json.dumps(body).encode(), "clock-rid", "application/json")


class AlpacaPaperRuntimeClockGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = SideEffectLedger(Path(self.tmp.name) / "effects.db")
        self.credentials = AlpacaPaperCredentials("paper-key", "paper-secret")
        self.policy = AlpacaPaperStrategyPolicy(strategy_id="minute-body-v1")

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, clock_request_fn):
        def forbidden(request, timeout):
            raise AssertionError("account/order transport must not be called when market clock blocks")

        return run_alpaca_paper_once(
            credentials=self.credentials,
            account_id="paper-account",
            symbol="AAPL",
            ledger=self.ledger,
            policy=self.policy,
            market_request_fn=market_ok,
            clock_request_fn=clock_request_fn,
            account_request_fn=forbidden,
            order_request_fn=forbidden,
            now_utc=NOW,
        )

    def test_unavailable_clock_blocks_without_side_effect_reservation(self):
        result = self._run(lambda request, timeout: _HttpResult(503, b"{}", "rid", "application/json"))
        self.assertEqual(result.status, "MARKET_CLOCK_UNAVAILABLE")
        self.assertIsNone(result.side_effect)

    def test_closed_market_blocks_without_side_effect_reservation(self):
        result = self._run(lambda request, timeout: clock_result("2026-09-11T00:01:00Z", False))
        self.assertEqual(result.status, "MARKET_CLOSED")
        self.assertIsNone(result.side_effect)

    def test_stale_clock_blocks_without_side_effect_reservation(self):
        result = self._run(lambda request, timeout: clock_result("2026-09-11T00:00:29Z"))
        self.assertEqual(result.status, "STALE_MARKET_CLOCK")
        self.assertIsNone(result.side_effect)

    def test_future_clock_blocks_without_side_effect_reservation(self):
        result = self._run(lambda request, timeout: clock_result("2026-09-11T00:01:31Z"))
        self.assertEqual(result.status, "FUTURE_MARKET_CLOCK")
        self.assertIsNone(result.side_effect)

    def test_clock_policy_is_part_of_side_effect_identity(self):
        from workflow_os.alpaca_market_data import AlpacaLatestBarObservation
        from workflow_os.alpaca_paper_runtime import evaluate_paper_observation

        observation = AlpacaLatestBarObservation(
            symbol="AAPL",
            timestamp="2026-09-11T00:00:00Z",
            open=100.0,
            high=101.0,
            low=99.9,
            close=100.2,
            volume=1000,
            trade_count=10,
            vwap=100.1,
        )
        first = evaluate_paper_observation(
            observation=observation,
            policy=AlpacaPaperStrategyPolicy(
                strategy_id="minute-body-v1", maximum_market_clock_age_seconds=30.0
            ),
            now_utc=NOW,
        )
        second = evaluate_paper_observation(
            observation=observation,
            policy=AlpacaPaperStrategyPolicy(
                strategy_id="minute-body-v1", maximum_market_clock_age_seconds=20.0
            ),
            now_utc=NOW,
        )
        self.assertEqual(first.action, "BUY")
        self.assertEqual(second.action, "BUY")
        self.assertNotEqual(first.client_order_id, second.client_order_id)


if __name__ == "__main__":
    unittest.main()
