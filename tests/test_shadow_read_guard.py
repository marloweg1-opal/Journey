import stat
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.shadow import _metadata_probe, _proposal_action_for


class ShadowReadGuardTests(unittest.TestCase):
    def test_denied_metadata_never_becomes_missing_or_actionable(self):
        for reason in ('SOURCE_HELD', 'POLICY_UNAVAILABLE', 'UNSUPPORTED_PATH'):
            with self.subTest(reason=reason), patch(
                'core.shadow.require_path_not_held', side_effect=PermissionError(reason)
            ), patch('core.shadow.os.lstat') as probe:
                state, explanation = _metadata_probe({'canonical_path': 'F:\\fixture'})
            probe.assert_not_called()
            self.assertEqual(state, 'UNREADABLE_DURING_SHADOW')
            self.assertIn(reason, explanation)
            self.assertIsNone(_proposal_action_for({}, state))

    def test_reparse_ancestor_blocks_leaf_probe(self):
        path = Path('R:\\junction\\fixture')
        calls = []

        def metadata(candidate):
            calls.append(candidate)
            return SimpleNamespace(st_mode=stat.S_IFDIR,
                                   st_file_attributes=0x400 if candidate == path.parent else 0)

        with patch('core.shadow.require_path_not_held'), patch('core.shadow.os.lstat', side_effect=metadata):
            state, _ = _metadata_probe({'canonical_path': str(path)})
        self.assertEqual(state, 'REPARSE_POINT_SKIPPED')
        self.assertNotIn(path, calls)
        self.assertEqual(calls[0], Path(path.anchor))

    def test_hold_arriving_between_ancestor_probes_stops_reads(self):
        with patch('core.shadow.require_path_not_held', side_effect=[
            None, None, None, PermissionError('SOURCE_HELD')
        ]), patch('core.shadow.os.lstat', return_value=SimpleNamespace(
            st_mode=stat.S_IFDIR, st_file_attributes=0
        )) as probe:
            state, _ = _metadata_probe({'canonical_path': 'R:\\folder\\fixture'})
        self.assertEqual(state, 'UNREADABLE_DURING_SHADOW')
        self.assertEqual(probe.call_count, 1)
