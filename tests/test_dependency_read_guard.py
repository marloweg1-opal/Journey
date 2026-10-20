import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.dependency_evidence import inspect_references
from core.patrol import live_discover
from dependency_fixture import inspect_references as inspect_fixture


class DependencyReadGuardTests(unittest.TestCase):
    def test_root_denial_precedes_every_target_probe(self):
        for reason in ('SOURCE_HELD', 'POLICY_UNAVAILABLE', 'UNSUPPORTED_PATH'):
            with self.subTest(reason=reason), patch(
                'core.read_guard.require_path_not_held', side_effect=PermissionError(reason)
            ), patch('core.patrol.os.lstat') as stat, patch('core.patrol.os.scandir') as scan:
                result = inspect_references(['asset.png'], ['F:\\fixture'])
            stat.assert_not_called()
            scan.assert_not_called()
            self.assertFalse(result['scope_coverage'][0]['complete'])
            self.assertIn(reason, result['scope_coverage'][0]['errors'][0]['error'])
            self.assertEqual(result['dependency_state'], 'UNKNOWN')
            self.assertFalse(result['dependency_clearance'])
            self.assertEqual(result['bytes_read'], 0)

    def test_leaf_hold_skips_metadata_and_preserves_other_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            held = root / 'held.ini'
            other = root / 'other.ini'
            held.write_text('held')
            other.write_text('other')
            import os
            original = os.lstat

            def guard(path):
                if Path(path) == held:
                    raise PermissionError('SOURCE_HELD')

            with patch('core.read_guard.require_path_not_held', side_effect=guard), patch(
                'core.patrol.os.lstat', wraps=original
            ) as stat:
                rows, coverage = live_discover(root)
            self.assertEqual([r['canonical_path'] for r in rows], [str(other)])
            self.assertFalse(coverage['complete'])
            self.assertFalse(any(Path(call.args[0]) == held for call in stat.call_args_list))

    def test_denial_after_discovery_blocks_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'fixture.ini'
            path.write_text('icon=asset.png')
            with patch('core.dependency_evidence.live_discover', return_value=(
                [{'canonical_path': str(path)}], {'complete': True}
            )), patch('core.dependency_evidence.require_path_not_held',
                      side_effect=PermissionError('POLICY_UNAVAILABLE')), patch('pathlib.Path.open') as opened:
                result = inspect_fixture(['asset.png'], [tmp])
            opened.assert_not_called()
            self.assertEqual(result['checked'], [])
            self.assertFalse(result['scope_coverage'][0]['content_inspection_complete'])
            self.assertFalse(result['target_observations'][0]['search_performed'])
            self.assertEqual(result['dependency_state'], 'UNKNOWN')
            self.assertIn('POLICY_UNAVAILABLE', result['errors'][0]['reason'])
