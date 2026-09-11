import unittest
from datetime import datetime, timezone
from dataclasses import replace
from decimal import Decimal

from workflow_os.alpaca_paper_execution_costs import evaluate_paper_execution_economics
from workflow_os.alpaca_paper_order_outcome import AlpacaPaperOrderOutcome
from workflow_os.alpaca_paper_position_accounting import (
    ALPACA_PAPER_POSITION_ACCOUNTING_POLICY_VERSION,
    match_closed_long_paper_position,
)


class AlpacaPaperPositionAccountingTests(unittest.TestCase):
    def _outcome(self, *, client_order_id, side, price, qty="2"):
        return AlpacaPaperOrderOutcome(
            external_order_id=f"external-{client_order_id}",
            client_order_id=client_order_id,
            symbol="AAPL",
            side=side,
            status="filled",
            ordered_qty=Decimal(qty),
            filled_qty=Decimal(qty),
            filled_avg_price=Decimal(price),
            submitted_at=datetime(2026, 9, 11, 8, 30, tzinfo=timezone.utc),
            filled_at=datetime(2026, 9, 11, 8, 30, 1, tzinfo=timezone.utc),
            terminal=True,
        )

    def _economics(self, *, client_order_id, side, reference, fill=None, qty="2"):
        return evaluate_paper_execution_economics(
            outcome=self._outcome(
                client_order_id=client_order_id,
                side=side,
                price=fill if fill is not None else reference,
                qty=qty,
            ),
            reference_price=reference,
        )

    def test_matches_one_fully_closed_long_position_after_modeled_costs(self):
        opening = self._economics(
            client_order_id="open-1",
            side="buy",
            reference="100",
        )
        closing = self._economics(
            client_order_id="close-1",
            side="sell",
            reference="110",
        )

        position = match_closed_long_paper_position(opening=opening, closing=closing)

        self.assertEqual(position.closed_qty, Decimal("2"))
        self.assertEqual(position.gross_reference_pnl_usd, Decimal("20"))
        self.assertEqual(position.modeled_total_execution_cost_usd, Decimal("0.630"))
        self.assertEqual(position.paper_realized_pnl_usd, Decimal("19.370"))
        self.assertEqual(
            position.policy_version,
            ALPACA_PAPER_POSITION_ACCOUNTING_POLICY_VERSION,
        )

    def test_losing_position_remains_negative_after_costs(self):
        opening = self._economics(
            client_order_id="open-loss",
            side="buy",
            reference="100",
        )
        closing = self._economics(
            client_order_id="close-loss",
            side="sell",
            reference="90",
        )

        position = match_closed_long_paper_position(opening=opening, closing=closing)

        self.assertEqual(position.gross_reference_pnl_usd, Decimal("-20"))
        self.assertLess(position.paper_realized_pnl_usd, Decimal("-20"))

    def test_partial_inventory_fails_closed(self):
        opening = self._economics(
            client_order_id="open-partial",
            side="buy",
            reference="100",
            qty="2",
        )
        closing = self._economics(
            client_order_id="close-partial",
            side="sell",
            reference="110",
            qty="1",
        )

        with self.assertRaisesRegex(ValueError, "partial inventory"):
            match_closed_long_paper_position(opening=opening, closing=closing)

    def test_wrong_direction_and_same_order_id_fail_closed(self):
        buy_one = self._economics(
            client_order_id="buy-1",
            side="buy",
            reference="100",
        )
        buy_two = self._economics(
            client_order_id="buy-2",
            side="buy",
            reference="110",
        )
        with self.assertRaisesRegex(ValueError, "buy then sell"):
            match_closed_long_paper_position(opening=buy_one, closing=buy_two)

        closing = self._economics(
            client_order_id="buy-1",
            side="sell",
            reference="110",
        )
        with self.assertRaisesRegex(ValueError, "distinct orders"):
            match_closed_long_paper_position(opening=buy_one, closing=closing)

    def test_tampered_execution_economics_fail_closed(self):
        opening = self._economics(
            client_order_id="open-tamper",
            side="buy",
            reference="100",
        )
        closing = self._economics(
            client_order_id="close-tamper",
            side="sell",
            reference="110",
        )
        tampered_closing = replace(
            closing,
            modeled_net_cash_flow_usd=closing.modeled_net_cash_flow_usd + Decimal("1"),
        )

        with self.assertRaisesRegex(ValueError, "internally inconsistent"):
            match_closed_long_paper_position(
                opening=opening,
                closing=tampered_closing,
            )

    def test_paper_position_never_proves_cash_or_live_authority(self):
        position = match_closed_long_paper_position(
            opening=self._economics(
                client_order_id="open-safe",
                side="buy",
                reference="100",
            ),
            closing=self._economics(
                client_order_id="close-safe",
                side="sell",
                reference="110",
            ),
        )

        self.assertFalse(position.proves_received_cash)
        self.assertFalse(position.proves_realized_cash_pnl)
        self.assertFalse(position.may_enter_live_execution)


if __name__ == "__main__":
    unittest.main()
