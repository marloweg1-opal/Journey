import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.patrol import live_discover


class DiscoveryBudgetTypeTests(unittest.TestCase):
    def assert_rejected_before_probe(self, key, value):
        with patch('core.read_guard.require_path_not_held') as guard, \
                patch('core.patrol.os.lstat') as metadata, \
                patch('core.patrol.os.scandir') as scan:
            with self.assertRaises(ValueError):
                live_discover('fixture', **{key: value})
            guard.assert_not_called()
            metadata.assert_not_called()
            scan.assert_not_called()

    def test_invalid_count_limits(self):
        for key in ('max_files', 'max_entries'):
            for value in (True, False, 0, -1, 1.5, '10', None, float('inf'), float('nan')):
                with self.subTest(key=key, value=value):
                    self.assert_rejected_before_probe(key, value)

    def test_invalid_depth_limits(self):
        for value in (True, False, -1, 1.5, '10', None, float('inf'), float('nan')):
            with self.subTest(value=value):
                self.assert_rejected_before_probe('max_depth', value)

    def test_invalid_time_limits(self):
        for value in (True, False, 0, -1, '10', None, float('inf'), float('-inf'),
                      float('nan'), 10 ** 500):
            with self.subTest(value=value):
                self.assert_rejected_before_probe('max_seconds', value)

    def test_zero_depth_and_fractional_time_keep_fixture_usable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'fixture.txt'
            path.write_bytes(b'fixture')
            with patch('core.read_guard.require_path_not_held'):
                rows, coverage = live_discover(path, max_depth=0, max_seconds=0.5)
                self.assertEqual([row['canonical_path'] for row in rows], [str(path)])
                self.assertTrue(coverage['complete'])
                rows, coverage = live_discover(tmp, max_depth=0, max_seconds=0.5)
                self.assertEqual(rows, [])
                self.assertFalse(coverage['complete'])
