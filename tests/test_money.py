import tempfile
import unittest
from pathlib import Path
import money

class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "queue.db"
        self.db = money.connect(self.path)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def add(self, ident="demo"):
        return money.enqueue(self.db, ident, "Synthetic task", "Unit test")

    def test_duplicate_and_conflict(self):
        self.assertTrue(self.add())
        self.assertFalse(self.add())
        with self.assertRaises(ValueError):
            money.enqueue(self.db, "demo", "changed", "test")
        self.assertEqual(len(money.rows(self.db)), 1)

    def test_claim_and_finish(self):
        self.add()
        self.assertEqual(money.claim(self.db, "a")["id"], "demo")
        second = money.connect(self.path)
        try:
            self.assertIsNone(money.claim(second, "b"))
        finally:
            second.close()
        with self.assertRaises(ValueError):
            money.finish(self.db, "demo", "b", "synthetic")
        with self.assertRaises(ValueError):
            money.finish(self.db, "demo", "a", "")
        money.finish(self.db, "demo", "a", "synthetic test evidence")
        self.assertEqual(money.rows(self.db)[0]["status"], "prepared")
        with self.assertRaises(ValueError):
            money.finish(self.db, "demo", "a", "again")

    def test_block_and_continue(self):
        self.add("one")
        self.add("two")
        self.assertEqual(money.claim(self.db, "a")["id"], "one")
        money.finish(self.db, "one", "a", "synthetic evidence", "owner approval needed")
        self.assertEqual(money.claim(self.db, "b")["id"], "two")
        r = money.report(self.db)
        self.assertEqual(r["task_counts"]["blocked"], 1)
        self.assertIsNone(r["actual_revenue"])
        self.assertIsNone(r["actual_cost"])

    def test_blank_fields(self):
        with self.assertRaises(ValueError):
            money.enqueue(self.db, "", "name", "acceptance")
        with self.assertRaises(ValueError):
            money.claim(self.db, "")

if __name__ == "__main__":
    unittest.main()
