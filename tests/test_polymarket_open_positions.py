import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from workflow_os.polymarket_paper_state import PolymarketPaperStore


class PolymarketOpenPositionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'paper.sqlite3'

    def tearDown(self):
        self.tmp.cleanup()

    def test_open_positions_returns_validated_durable_monitoring_state(self):
        store = PolymarketPaperStore(self.path)
        opened_at = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
        store.open_yes(
            market_id='m1', stake_usd=2, entry_price=.5,
            entry_fair_probability=.7, opened_at=opened_at,
        )
        positions = store.open_positions()
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0].market_id, 'm1')
        self.assertEqual(positions[0].stake_usd, 2)
        self.assertEqual(positions[0].entry_price, .5)
        self.assertEqual(positions[0].entry_fair_probability, .7)
        self.assertEqual(positions[0].opened_at, opened_at)

    def test_closed_position_is_not_returned(self):
        store = PolymarketPaperStore(self.path)
        store.open_yes(market_id='m1', stake_usd=1, entry_price=.5, entry_fair_probability=.7)
        store.close_yes(market_id='m1', exit_price=.6)
        self.assertEqual(store.open_positions(), ())

    def test_corrupt_opened_at_fails_closed(self):
        store = PolymarketPaperStore(self.path)
        store.open_yes(market_id='m1', stake_usd=1, entry_price=.5, entry_fair_probability=.7)
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE paper_positions SET opened_at='not-a-date' WHERE market_id='m1'")
        with self.assertRaises(RuntimeError):
            store.open_positions()

    def test_corrupt_position_economics_fail_closed(self):
        store = PolymarketPaperStore(self.path)
        store.open_yes(market_id='m1', stake_usd=1, entry_price=.5, entry_fair_probability=.7)
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE paper_positions SET entry_price=0 WHERE market_id='m1'")
        with self.assertRaises(RuntimeError):
            store.open_positions()


if __name__ == '__main__':
    unittest.main()
