import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.shadow import run_shadow  # noqa: E402
from db.database import initialize_schema  # noqa: E402


class ShadowModeTests(unittest.TestCase):
    def _conn(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        initialize_schema(conn)
        return conn

    def test_shadow_run_records_summary_findings_and_reports_without_mutation(self):
        conn = self._conn()
        conn.execute(
            """INSERT INTO files (canonical_path, hash, size_bytes, modified_at, status)
            VALUES (?, ?, ?, ?, 'present');""",
            (r"R:\Downloads2\new_asset_sheet.png", "abc", 10, "2026-09-14T10:00:00"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            summary = run_shadow(
                conn,
                scope=r"R:\Downloads2",
                docs_root=tmp,
                verify_current=False,
            )

            self.assertEqual(summary["managed_file_mutations"], 0)
            self.assertEqual(summary["files_examined"], 1)
            self.assertEqual(summary["files_implicated"], 1)
            self.assertEqual(summary["review_families"], 1)
            self.assertGreaterEqual(summary["estimated_human_decisions"], 1)
            self.assertEqual(summary["resolution_strategies"]["MIGRATE"], 1)
            self.assertTrue(Path(summary["report_path"]).exists())
            self.assertTrue(Path(summary["evidence_path"]).exists())

            run = conn.execute("SELECT * FROM shadow_runs;").fetchone()
            self.assertEqual(run["status"], "complete")
            self.assertEqual(run["files_examined"], 1)
            finding = conn.execute("SELECT * FROM stewardship_findings;").fetchone()
            self.assertEqual(finding["shadow_run_id"], run["id"])
            self.assertEqual(finding["placement_status"], "LEGACY_PATH")
            proposal = conn.execute("SELECT * FROM stewardship_proposals;").fetchone()
            self.assertEqual(proposal["shadow_run_id"], run["id"])
            self.assertEqual(proposal["status"], "pending")
        conn.close()

    def test_shadow_run_marks_changed_metadata_unstable_and_blocks_proposal(self):
        conn = self._conn()
        with tempfile.TemporaryDirectory() as tmp:
            candidate = Path(tmp) / "carebloom_badge.png"
            candidate.write_text("changed", encoding="utf-8")
            conn.execute(
                """INSERT INTO files (canonical_path, hash, size_bytes, modified_at, status)
                VALUES (?, ?, ?, ?, 'present');""",
                (str(candidate), "abc", 999, "2026-09-14T10:00:00"),
            )
            summary = run_shadow(
                conn,
                scope=str(candidate.parent),
                docs_root=tmp,
                verify_current=True,
            )

            self.assertEqual(summary["files_implicated"], 1)
            finding = conn.execute("SELECT * FROM stewardship_findings;").fetchone()
            self.assertEqual(finding["placement_status"], "LEDGER_METADATA_DRIFT")
            proposal_count = conn.execute("SELECT COUNT(*) AS c FROM stewardship_proposals;").fetchone()["c"]
            self.assertEqual(proposal_count, 0)
        conn.close()


if __name__ == "__main__":
    unittest.main()
