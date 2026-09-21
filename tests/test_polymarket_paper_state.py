import tempfile
import unittest
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

    def test_duplicate_market_fails_closed(self):
        store = PolymarketPaperStore(self.path)
        store.open_yes(market_id='m1', stake_usd=1, entry_price=.5, entry_fair_probability=.7)
        with self.assertRaises(Exception):
            store.open_yes(market_id='m1', stake_usd=1, entry_price=.5, entry_fair_probability=.7)

    def test_stopped_account_cannot_open(self):
        store = PolymarketPaperStore(self.path)
        store.stop('DRAWDOWN_LIMIT')
        with self.assertRaises(RuntimeError):
            store.open_yes(market_id='m1', stake_usd=1, entry_price=.5, entry_fair_probability=.7)
        self.assertTrue(store.account().stopped)


if __name__ == '__main__':
    unittest.main()
