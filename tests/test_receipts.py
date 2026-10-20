import json
import sqlite3
import unittest

from core.receipts import list_receipts


class ReceiptTests(unittest.TestCase):
    def test_receipts_show_undo_only_for_applied_non_undo_operations(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """CREATE TABLE action_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_type TEXT NOT NULL,
                tier INTEGER NOT NULL,
                target_path TEXT,
                previous_state TEXT,
                new_state TEXT,
                status TEXT NOT NULL DEFAULT 'applied',
                performed_at TEXT NOT NULL DEFAULT '2026-09-09 12:00:00',
                reversed_at TEXT
            );"""
        )
        conn.execute(
            """INSERT INTO action_log
               (action_type, tier, target_path, previous_state, new_state, status)
               VALUES (?, ?, ?, ?, ?, ?);""",
            ("file_shortcut", 2, "R:\\Thing", json.dumps({"source": "A"}), json.dumps({"shortcut": "B"}), "applied"),
        )
        conn.execute(
            """INSERT INTO action_log
               (action_type, tier, target_path, previous_state, new_state, status, reversed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?);""",
            ("file_move", 2, "R:\\Old", json.dumps({"source": "A"}), json.dumps({"dest": "B"}), "reversed", "2026-09-09 12:10:00"),
        )
        conn.execute(
            """INSERT INTO action_log
               (action_type, tier, target_path, previous_state, new_state, status)
               VALUES (?, ?, ?, ?, ?, ?);""",
            ("undo:file_move", 2, "R:\\Old", json.dumps({"dest": "B"}), json.dumps({"source": "A"}), "applied"),
        )
        conn.commit()

        receipts = list_receipts(conn, limit=10)
        by_action = {receipt["action_type"]: receipt for receipt in receipts}

        self.assertFalse(by_action["file_shortcut"]["undo_available"])
        self.assertEqual(by_action["file_shortcut"]["undo_state"], 'UNDO_REQUIRES_REVIEW')
        self.assertIsNone(by_action["file_shortcut"]["undo_command"])
        self.assertFalse(by_action["file_move"]["undo_available"])
        self.assertFalse(by_action["undo:file_move"]["undo_available"])
        self.assertEqual(by_action["file_shortcut"]["before"]["keys"], ["source"])
        conn.close()


if __name__ == "__main__":
    unittest.main()
