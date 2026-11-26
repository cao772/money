import tempfile
import unittest
from pathlib import Path

import money
import notion_queue as bridge


class BridgeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "queue.db"
        self.db = bridge.open_db(self.path, False)
        self.addCleanup(self.db.close)
        self.card = dict(task_id="example:build1", page_id="00000000-0000-4000-8000-000000000001",
                         opportunity_id="example", title="Synthetic build", acceptance="Compare hashes")

    def test_dry_run_conflicts_and_readback(self):
        trial = bridge.open_db(self.path, True)
        self.addCleanup(trial.close)
        self.assertTrue(bridge.import_card(trial, self.card)["created"])
        self.assertEqual(money.rows(self.db), [])
        self.assertTrue(bridge.import_card(self.db, self.card)["created"])
        self.assertFalse(bridge.import_card(self.db, self.card)["created"])
        with self.assertRaises(ValueError):
            bridge.import_card(self.db, {**self.card, "page_id": "00000000-0000-4000-8000-000000000002"})
        task = money.claim(self.db, "worker", self.card["task_id"], 2)
        with self.assertRaises(ValueError):
            bridge.receipt(self.db, task["id"])
        money.finish(self.db, task["id"], "worker", "synthetic verification", lease_token=task["lease_token"])
        item = bridge.receipt(self.db, task["id"])
        snapshot = {"id": self.card["page_id"], "text": "Previous content"}
        with self.assertRaises(ValueError):
            bridge.confirm(self.db, task["id"], snapshot)
        snapshot["text"] += item["request"]["content"]
        with self.assertRaises(ValueError):
            bridge.confirm(self.db, task["id"], {**snapshot, "id": "00000000-0000-4000-8000-000000000002"})
        for _ in range(2):
            self.assertTrue(bridge.confirm(self.db, task["id"], snapshot)["confirmed"])
        self.assertTrue(bridge.receipt(self.db, task["id"])["confirmed"])

    def test_expired_lease_is_fenced_even_for_same_worker(self):
        bridge.import_card(self.db, self.card)
        task_id = self.card["task_id"]
        old = money.claim(self.db, "daily", task_id, 2)
        self.assertIsNone(money.claim(self.db, "daily", task_id, 2))
        with self.db:
            self.db.execute("UPDATE leases SET expires_at='2000-01-01' WHERE task_id=?", (task_id,))
        with self.assertRaises(ValueError):
            money.finish(self.db, task_id, "daily", "stale", lease_token=old["lease_token"])
        new = money.claim(self.db, "daily", task_id, 2)
        with self.assertRaises(ValueError):
            money.finish(self.db, task_id, "daily", "stale", lease_token=old["lease_token"])
        money.finish(self.db, task_id, "daily", "synthetic", "owner decision", new["lease_token"])
        self.assertIn("owner decision", bridge.receipt(self.db, task_id)["request"]["content"])
