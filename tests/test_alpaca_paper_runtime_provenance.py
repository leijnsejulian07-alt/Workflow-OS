import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from workflow_os.alpaca_market_data import AlpacaLatestBarObservation
from workflow_os.alpaca_paper_runtime import (
    ALPACA_PAPER_ACTION,
    AlpacaPaperStrategyPolicy,
    evaluate_paper_observation,
    run_alpaca_paper_once,
)
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


class AlpacaPaperRuntimeProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = SideEffectLedger(Path(self.tmp.name) / "effects.db")
        self.credentials = AlpacaPaperCredentials("paper-key", "paper-secret")

    def tearDown(self):
        self.tmp.cleanup()

    def test_policy_parameter_change_gets_distinct_side_effect_identity(self):
        posted = []

        def order_ok(request, timeout):
            payload = json.loads(request.data.decode())
            posted.append(payload)
            return _HttpResult(
                200,
                json.dumps({
                    "id": f"paper-order-{len(posted)}",
                    "client_order_id": payload["client_order_id"],
                }).encode(),
                "order-rid",
                "application/json",
            )

        first = run_alpaca_paper_once(
            credentials=self.credentials,
            account_id="paper-account",
            symbol="AAPL",
            ledger=self.ledger,
            policy=AlpacaPaperStrategyPolicy(strategy_id="minute-body-v1", quantity_shares=0.01),
            market_request_fn=market_ok,
            clock_request_fn=clock_ok,
            account_request_fn=account_ok,
            order_request_fn=order_ok,
            now_utc=NOW,
        )
        second = run_alpaca_paper_once(
            credentials=self.credentials,
            account_id="paper-account",
            symbol="AAPL",
            ledger=self.ledger,
            policy=AlpacaPaperStrategyPolicy(strategy_id="minute-body-v1", quantity_shares=0.02),
            market_request_fn=market_ok,
            clock_request_fn=clock_ok,
            account_request_fn=account_ok,
            order_request_fn=order_ok,
            now_utc=NOW,
        )

        self.assertEqual(first.status, "EXECUTED")
        self.assertEqual(second.status, "EXECUTED")
        self.assertEqual(len(posted), 2)
        self.assertNotEqual(posted[0]["client_order_id"], posted[1]["client_order_id"])
        self.assertEqual(posted[0]["qty"], "0.01")
        self.assertEqual(posted[1]["qty"], "0.02")

    def test_succeeded_record_with_wrong_payload_fingerprint_is_not_trusted(self):
        policy = AlpacaPaperStrategyPolicy(strategy_id="minute-body-v1")
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
        decision = evaluate_paper_observation(observation=observation, policy=policy, now_utc=NOW)
        self.assertEqual(decision.action, "BUY")
        self.assertIsNotNone(decision.client_order_id)

        self.ledger.reserve(
            idempotency_key=decision.client_order_id,
            action=ALPACA_PAPER_ACTION,
            target="ALPACA_PAPER:paper-account",
            payload={"tampered": True},
            max_attempts=2,
        )
        self.ledger.begin_attempt(decision.client_order_id)
        self.ledger.mark_succeeded(decision.client_order_id, external_reference="wrong-order")

        def forbidden(request, timeout):
            raise AssertionError("wrongly-bound succeeded side effect must never reach transport")

        with self.assertRaisesRegex(ValueError, "different side effect"):
            run_alpaca_paper_once(
                credentials=self.credentials,
                account_id="paper-account",
                symbol="AAPL",
                ledger=self.ledger,
                policy=policy,
                market_request_fn=market_ok,
                clock_request_fn=forbidden,
                account_request_fn=forbidden,
                order_request_fn=forbidden,
                now_utc=NOW,
            )


if __name__ == "__main__":
    unittest.main()
