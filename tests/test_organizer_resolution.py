import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.organizer import analyze_and_propose  # noqa: E402
from db.database import initialize_schema  # noqa: E402


class OrganizerResolutionTests(unittest.TestCase):
    def test_generic_organizer_creates_family_review_not_shortcut_items(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        initialize_schema(conn)
        conn.execute(
            """INSERT INTO files (canonical_path, hash, size_bytes, modified_at, status)
            VALUES (?, ?, ?, ?, 'present');""",
            (r"R:\Downloads2\carebloom_data.json", "abc", 10, "2026-09-15T10:00:00"),
        )

        result = analyze_and_propose(conn, r"R:\Downloads2")

        self.assertEqual(result["status"], "proposed")
        self.assertEqual(result["proposals_written"], 1)
        proposal = conn.execute("SELECT description FROM proposals;").fetchone()
        self.assertIn("Placement resolution family", proposal["description"])
        self.assertIn("LEAVE, REFERENCE, MIGRATE", proposal["description"])
        item_count = conn.execute("SELECT COUNT(*) AS c FROM proposal_items;").fetchone()["c"]
        self.assertEqual(item_count, 0)
        conn.close()


if __name__ == "__main__":
    unittest.main()
