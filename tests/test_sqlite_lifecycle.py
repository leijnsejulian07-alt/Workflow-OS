from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from workflow_os.sqlite_lifecycle import managed_connection


class SQLiteLifecycleTests(unittest.TestCase):
    def test_connection_is_closed_after_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "success.sqlite"
            connection = sqlite3.connect(db_path)
            with managed_connection(connection) as db:
                db.execute("CREATE TABLE sample(value INTEGER)")
                db.execute("INSERT INTO sample(value) VALUES(1)")
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute("SELECT 1")
            db_path.unlink()

    def test_connection_rolls_back_and_closes_after_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "rollback.sqlite"
            seed = sqlite3.connect(db_path)
            seed.execute("CREATE TABLE sample(value INTEGER)")
            seed.commit()
            seed.close()

            connection = sqlite3.connect(db_path)
            with self.assertRaisesRegex(RuntimeError, "boom"):
                with managed_connection(connection) as db:
                    db.execute("INSERT INTO sample(value) VALUES(1)")
                    raise RuntimeError("boom")
            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute("SELECT 1")

            verify = sqlite3.connect(db_path)
            try:
                count = verify.execute("SELECT COUNT(*) FROM sample").fetchone()[0]
            finally:
                verify.close()
            self.assertEqual(count, 0)
            db_path.unlink()


if __name__ == "__main__":
    unittest.main()
