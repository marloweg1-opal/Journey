"""Legacy entry points must stop before plan access or filesystem work."""
import unittest
from pathlib import Path
from unittest.mock import patch

from core import profile_migration


class LegacyExecutionHoldTests(unittest.TestCase):
    def assert_held(self, executor, **kwargs):
        with patch.object(Path, 'read_text') as reader, \
                patch.object(Path, 'mkdir') as mkdir, \
                patch('shutil.copy2') as copier, \
                patch.object(Path, 'write_text') as writer:
            with self.assertRaisesRegex(PermissionError, 'STEWARDSHIP_REVIEW_REQUIRED'):
                executor('not-a-real-plan.json', **kwargs)
            reader.assert_not_called()
            mkdir.assert_not_called()
            copier.assert_not_called()
            writer.assert_not_called()

    def test_profile_staging_stops_before_plan_access(self):
        self.assert_held(profile_migration.execute_profile_migration_map)
