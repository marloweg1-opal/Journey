"""Policy-store diagnostics: clear causes without expanding authority."""
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import sqlite3

from journey_navigator.links import Boundaries, ProtectedPath


class SourcePolicyDiagnosticsTests(TestCase):
    def test_readonly_policy_store_remains_readable(self):
        with TemporaryDirectory() as temp:
            store = Path(temp) / "policy.sqlite"
            with closing(sqlite3.connect(store)) as conn, conn:
                conn.execute("CREATE TABLE source_entries (id INTEGER)")
                conn.execute("INSERT INTO source_entries VALUES (7)")
            self.assertEqual(
                Boundaries._rows(store, "SELECT id FROM source_entries", "source_entries"),
                [(7,)],
            )

    def test_locked_policy_store_is_a_hold_not_a_file_policy_denial(self):
        with TemporaryDirectory() as temp:
            store = Path(temp) / "policy.sqlite"
            store.touch()
            with patch("journey_navigator.links.sqlite3.connect",
                       side_effect=sqlite3.OperationalError("database is locked")):
                with self.assertRaisesRegex(ProtectedPath, "database is busy"):
                    Boundaries._rows(store, "SELECT 1", "test")

    def test_invalid_database_has_actionable_fail_closed_diagnostic(self):
        with TemporaryDirectory() as temp:
            store = Path(temp) / "policy.sqlite"
            store.write_bytes(b"not sqlite")
            with self.assertRaisesRegex(ProtectedPath, "policy-store health"):
                Boundaries._rows(store, "SELECT 1", "test")

    def test_missing_optional_store_stays_missing_and_no_file_is_created(self):
        with TemporaryDirectory() as temp:
            store = Path(temp) / "not-created.sqlite"
            self.assertEqual(Boundaries._rows(store, "SELECT 1", "test", optional_table=True), [])
            self.assertFalse(store.exists())
