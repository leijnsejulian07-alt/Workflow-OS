import sqlite3
import tempfile
import unittest
from pathlib import Path

from workflow_os.polymarket_paper_state import PolymarketPaperStore


class PolymarketPaperCorruptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'paper.sqlite3'
        self.store = PolymarketPaperStore(self.path, starting_bankroll_usd=50)

    def tearDown(self):
        self.tmp.cleanup()

    def _corrupt_account(self, assignment: str) -> None:
        with sqlite3.connect(self.path) as db:
            db.execute(f'UPDATE paper_account SET {assignment} WHERE singleton=1')

    def test_nonfinite_cash_fails_closed_on_read(self):
        self._corrupt_account("bankroll_usd='NaN'")
        with self.assertRaises(RuntimeError):
            self.store.account()

    def test_cash_above_peak_fails_closed_on_read(self):
        self._corrupt_account('bankroll_usd=51')
        with self.assertRaises(RuntimeError):
            self.store.account()

    def test_invalid_stop_state_fails_closed_on_read(self):
        self._corrupt_account('stopped=2')
        with self.assertRaises(RuntimeError):
            self.store.account()

    def test_corrupt_account_blocks_open_before_debit(self):
        self._corrupt_account('bankroll_usd=51')
        with self.assertRaises(RuntimeError):
            self.store.open_yes(market_id='m1', stake_usd=1, entry_price=.5, entry_fair_probability=.7)
        self.assertEqual(self.store.open_count(), 0)

    def test_corrupt_account_blocks_close_before_position_mutation(self):
        self.store.open_yes(market_id='m1', stake_usd=1, entry_price=.5, entry_fair_probability=.7)
        self._corrupt_account('stopped=2')
        with self.assertRaises(RuntimeError):
            self.store.close_yes(market_id='m1', exit_price=.6)
        self.assertEqual(self.store.open_count(), 1)


if __name__ == '__main__':
    unittest.main()
