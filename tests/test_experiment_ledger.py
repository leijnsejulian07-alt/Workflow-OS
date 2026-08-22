import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from workflow_os.experiment_ledger import ExperimentLedger


class ExperimentLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "workflow-os.sqlite3"
        self.ledger = ExperimentLedger(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_reservation_is_persistent_and_idempotent(self):
        first = self.ledger.reserve_first_experiment(
            opportunity_id="op-1",
            experiment_key="exp-1",
            reserved_at="2026-08-22T10:00:00+00:00",
        )
        again = self.ledger.reserve_first_experiment(
            opportunity_id="op-1",
            experiment_key="exp-1",
            reserved_at="2026-08-22T10:00:00+00:00",
        )
        self.assertEqual(first, again)
        self.assertFalse(self.ledger.may_reserve_first_experiment("op-1"))

    def test_second_first_experiment_for_same_opportunity_fails_closed(self):
        self.ledger.reserve_first_experiment(
            opportunity_id="op-1",
            experiment_key="exp-1",
            reserved_at="2026-08-22T10:00:00+00:00",
        )
        with self.assertRaises(ValueError):
            self.ledger.reserve_first_experiment(
                opportunity_id="op-1",
                experiment_key="exp-2",
                reserved_at="2026-08-22T10:05:00+00:00",
            )

    def test_experiment_key_cannot_move_between_opportunities(self):
        self.ledger.reserve_first_experiment(
            opportunity_id="op-1",
            experiment_key="exp-1",
            reserved_at="2026-08-22T10:00:00+00:00",
        )
        with self.assertRaises(ValueError):
            self.ledger.reserve_first_experiment(
                opportunity_id="op-2",
                experiment_key="exp-1",
                reserved_at="2026-08-22T10:05:00+00:00",
            )

    def test_consumed_transition_is_idempotent(self):
        self.ledger.reserve_first_experiment(
            opportunity_id="op-1",
            experiment_key="exp-1",
            reserved_at="2026-08-22T10:00:00+00:00",
        )
        first = self.ledger.mark_consumed("op-1")
        again = self.ledger.mark_consumed("op-1")
        self.assertEqual(first.status, "CONSUMED")
        self.assertEqual(first, again)

    def test_unknown_consumption_fails_closed(self):
        with self.assertRaises(ValueError):
            self.ledger.mark_consumed("missing")

    def test_naive_timestamp_and_invalid_identifiers_fail_closed(self):
        with self.assertRaises(ValueError):
            self.ledger.reserve_first_experiment(
                opportunity_id="op-1",
                experiment_key="exp-1",
                reserved_at="2026-08-22T10:00:00",
            )
        with self.assertRaises(ValueError):
            self.ledger.may_reserve_first_experiment(" ")


if __name__ == "__main__":
    unittest.main()
