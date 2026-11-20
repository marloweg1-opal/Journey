"""Regression coverage for existing production protection-schema lookups."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
import sqlite3

from journey_navigator.guided import Guided
from journey_navigator.links import Boundaries


class DuplicatePolicySchemaTests(TestCase):
    def test_real_schema_columns_block_protected_paths_and_active_dependents(self):
        with TemporaryDirectory() as temp:
            store = Path(temp) / "ark.sqlite"
            with sqlite3.connect(store) as connection:
                connection.execute("CREATE TABLE protected_paths(path_prefix TEXT, reason TEXT)")
                connection.execute("CREATE TABLE file_dependents(canonical_path TEXT, status TEXT)")
                connection.execute("INSERT INTO protected_paths VALUES (?,?)", (str(Path(temp) / "protected"), "fixture"))
                connection.execute("INSERT INTO file_dependents VALUES (?,?)", (str(Path(temp) / "needed.png"), "active"))
                connection.execute("INSERT INTO file_dependents VALUES (?,?)", (str(Path(temp) / "retired.png"), "stale"))
            policy = Boundaries(perception_store=store)
            fake = SimpleNamespace(workbench=SimpleNamespace(policy=policy), conn=None)
            with patch("journey_navigator.guided.executor.is_protected", return_value=False), \
                 patch("journey_navigator.guided.executor.get_active_dependents", return_value=[]):
                with self.assertRaisesRegex(PermissionError, "protection or active dependency"):
                    Guided.require_unprotected(fake, Path(temp) / "protected" / "child.png")
                with self.assertRaisesRegex(PermissionError, "protection or active dependency"):
                    Guided.require_unprotected(fake, Path(temp) / "needed.png")
                Guided.require_unprotected(fake, Path(temp) / "retired.png")
                Guided.require_unprotected(fake, Path(temp) / "unrelated.png")
