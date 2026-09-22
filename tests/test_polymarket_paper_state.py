import math
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from workflow_os.polymarket_paper_state import PolymarketPaperStore


class PolymarketPaperStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'paper.sqlite3'

    def tearDown(self):
        self.tmp.cleanup()

    def test_open_close_survives_restart_and_reconciles_cash(self):
        store = PolymarketPaperStore(self.path, starting_bankroll_usd=50)
        store.open_yes(market_id='m1', stake_usd=3, entry_price=.60, entry_fair_probability=.72)
        self.assertEqual(store.account().bankroll_usd, 47)
        self.assertEqual(store.open_count(), 1)

        restarted = PolymarketPaperStore(self.path, starting_bankroll_usd=999)
        self.assertEqual(restarted.account().bankroll_usd, 47)
        pnl = restarted.close_yes(market_id='m1', exit_price=.72)
        self.assertAlmostEqual(pnl, .6)
        self.assertAlmostEqual(restarted.account().bankroll_usd, 50.6)
        self.assertAlmostEqual(restarted.account().realized_pnl_usd, .6)
        self.assertAlmostEqual(restarted.account().peak_bankroll_usd, 50.6)
        self.assertEqual(restarted.open_count(), 0)

    def test_duplicate_market_fails_closed_without_second_debit(self):
        store = PolymarketPaperStore(self.path)
        store.open_yes(market_id='m1', stake_usd=1, entry_price=.5, entry_fair_probability=.7)
        with self.assertRaises(ValueError):
            store.open_yes(market_id='m1', stake_usd=1, entry_price=.5, entry_fair_probability=.7)
        self.assertEqual(store.open_count(), 1)
        self.assertEqual(store.account().bankroll_usd, 49)

    def test_stopped_account_cannot_open(self):
        store = PolymarketPaperStore(self.path)
        store.stop('DRAWDOWN_LIMIT')
        with self.assertRaises(RuntimeError):
            store.open_yes(market_id='m1', stake_usd=1, entry_price=.5, entry_fair_probability=.7)
        self.assertTrue(store.account().stopped)

    def test_nonfinite_values_fail_closed_without_mutating_ledger(self):
        store = PolymarketPaperStore(self.path)
        for stake in (math.nan, math.inf, -math.inf, True):
            with self.subTest(stake=stake):
                with self.assertRaises(ValueError):
                    store.open_yes(market_id='m1', stake_usd=stake, entry_price=.5, entry_fair_probability=.7)
        self.assertEqual(store.open_count(), 0)
        self.assertEqual(store.account().bankroll_usd, 50)

    def test_invalid_starting_bankroll_fails_before_database_initialization(self):
        for bankroll in (math.nan, math.inf, -1, 0, True):
            with self.subTest(bankroll=bankroll):
                candidate = Path(self.tmp.name) / f'invalid-{repr(bankroll)}.sqlite3'
                with self.assertRaises(ValueError):
                    PolymarketPaperStore(candidate, starting_bankroll_usd=bankroll)
                self.assertFalse(candidate.exists())

    def test_nonfinite_exit_price_does_not_close_position(self):
        store = PolymarketPaperStore(self.path)
        store.open_yes(market_id='m1', stake_usd=1, entry_price=.5, entry_fair_probability=.7)
        for exit_price in (math.nan, math.inf, -math.inf, True):
            with self.subTest(exit_price=exit_price):
                with self.assertRaises(ValueError):
                    store.close_yes(market_id='m1', exit_price=exit_price)
        self.assertEqual(store.open_count(), 1)
        self.assertEqual(store.account().bankroll_usd, 49)

    def test_settlement_overflow_fails_closed_without_closing_position(self):
        store = PolymarketPaperStore(self.path)
        store.open_yes(market_id='m1', stake_usd=1, entry_price=5e-324, entry_fair_probability=.7)
        with self.assertRaises(ValueError):
            store.close_yes(market_id='m1', exit_price=1)
        self.assertEqual(store.open_count(), 1)
        self.assertEqual(store.account().bankroll_usd, 49)
        self.assertEqual(store.account().realized_pnl_usd, 0)

    def test_naive_or_non_datetime_opened_at_fails_closed_without_debit(self):
        store = PolymarketPaperStore(self.path)
        for opened_at in (datetime(2026, 9, 22, 1, 0), '2026-09-22T01:00:00Z', True):
            with self.subTest(opened_at=opened_at):
                with self.assertRaises(ValueError):
                    store.open_yes(
                        market_id='m1',
                        stake_usd=1,
                        entry_price=.5,
                        entry_fair_probability=.7,
                        opened_at=opened_at,
                    )
        self.assertEqual(store.open_count(), 0)
        self.assertEqual(store.account().bankroll_usd, 50)

    def test_aware_opened_at_is_normalized_to_utc(self):
        store = PolymarketPaperStore(self.path)
        store.open_yes(
            market_id='m1',
            stake_usd=1,
            entry_price=.5,
            entry_fair_probability=.7,
            opened_at=datetime(2026, 9, 22, 1, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(store.open_count(), 1)
        self.assertEqual(store.account().bankroll_usd, 49)


if __name__ == '__main__':
    unittest.main()
