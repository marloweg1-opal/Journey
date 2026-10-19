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

    def test_powershell_profile_cleanup_holds_execute_before_plan_access(self):
        script_path = Path(__file__).resolve().parents[1] / 'cleanup_r_user_profiles.ps1'
        script = script_path.read_text(encoding='utf-8')

        kill_switch = script.index('$KillSwitch =')
        execution_hold = script.index('if ($Execute) {')
        stage_access = script.index('if (-not (Test-Path -LiteralPath $StageResult')
        first_mutation = script.index('New-Item -ItemType Directory -Force -Path $MoveRoot')

        self.assertLess(kill_switch, execution_hold)
        self.assertLess(execution_hold, stage_access)
        self.assertLess(execution_hold, first_mutation)
        self.assertIn('exit 3', script[execution_hold:stage_access])
        self.assertIn('RESULT: HELD. No files were moved or removed.', script)
        self.assertIn('RESULT: PREVIEW COMPLETE. No files were moved or removed.', script)
        self.assertNotIn('cleanup_r_user_profiles.ps1 -Execute', script)
