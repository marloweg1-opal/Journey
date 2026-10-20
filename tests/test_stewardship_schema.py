import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from db.database import initialize_schema  # noqa: E402


class StewardshipSchemaTests(unittest.TestCase):
    def test_stewardship_records_are_separate_tables(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        initialize_schema(conn)

        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table';").fetchall()
        }

        self.assertIn("stewardship_file_identities", tables)
        self.assertIn("stewardship_findings", tables)
        self.assertIn("stewardship_proposals", tables)
        self.assertIn("stewardship_operations", tables)
        self.assertIn("stewardship_operation_events", tables)
        conn.close()

    def test_operation_state_and_commit_phase_defaults_are_persisted(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        initialize_schema(conn)

        conn.execute(
            """INSERT INTO stewardship_operations
            (capability_id, owner, domain, operation, idempotency_key)
            VALUES (?, ?, ?, ?, ?);""",
            ("placement-route", "cloverstone", "placement", "shadow", "shadow:test:1"),
        )
        row = conn.execute("SELECT state, commit_phase FROM stewardship_operations;").fetchone()

        self.assertEqual(row["state"], "PROPOSED")
        self.assertEqual(row["commit_phase"], "PLANNED")
        conn.close()

    def test_finding_proposal_operation_event_chain_can_be_recorded(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        initialize_schema(conn)

        cur = conn.execute(
            """INSERT INTO stewardship_findings
            (finding_type, subject_type, path, placement_status, reason, confidence, recommended_action)
            VALUES (?, ?, ?, ?, ?, ?, ?);""",
            ("placement", "folder", r"R:\Downloads2", "LEGACY_PATH", "legacy intake alias", 0.8, "review_legacy_mapping"),
        )
        finding_id = cur.lastrowid
        cur = conn.execute(
            """INSERT INTO stewardship_proposals
            (finding_id, description, proposed_action, confidence, risk, preview_available)
            VALUES (?, ?, ?, ?, ?, ?);""",
            (finding_id, "Route Downloads2 to En_Route", "propose_route", 0.8, "green", 1),
        )
        proposal_id = cur.lastrowid
        cur = conn.execute(
            """INSERT INTO stewardship_operations
            (proposal_id, capability_id, owner, domain, operation, state, idempotency_key)
            VALUES (?, ?, ?, ?, ?, ?, ?);""",
            (proposal_id, "placement-route", "cloverstone", "placement", "shadow", "PREVIEWED", "shadow:test:2"),
        )
        operation_id = cur.lastrowid
        conn.execute(
            """INSERT INTO stewardship_operation_events
            (operation_id, event_type, commit_phase, path, status)
            VALUES (?, ?, ?, ?, ?);""",
            (operation_id, "shadow_previewed", "PLANNED", r"R:\Downloads2", "observed"),
        )

        count = conn.execute("SELECT COUNT(*) AS count FROM stewardship_operation_events;").fetchone()["count"]
        self.assertEqual(count, 1)
        conn.close()


if __name__ == "__main__":
    unittest.main()
