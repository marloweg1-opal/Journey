import unittest
from unittest.mock import patch

from core.dependency_evidence import inspect_references


class DependencyBudgetTypeTests(unittest.TestCase):
    def test_invalid_counts_rejected_before_discovery(self):
        for key in ('max_files', 'max_bytes'):
            for value in (True, False, 0, -1, 1.5, '10', None, float('inf'), float('nan')):
                with self.subTest(key=key, value=value), patch(
                    'core.dependency_evidence.live_discover'
                ) as discover, patch('pathlib.Path.open') as opened:
                    with self.assertRaises(ValueError):
                        inspect_references([], ['fixture'], **{key: value})
                    discover.assert_not_called()
                    opened.assert_not_called()

    def test_invalid_time_rejected_before_discovery(self):
        for value in (True, False, 0, -1, '10', None, float('inf'), float('-inf'),
                      float('nan'), 10 ** 500):
            with self.subTest(value=value), patch(
                'core.dependency_evidence.live_discover'
            ) as discover, patch('pathlib.Path.open') as opened:
                with self.assertRaises(ValueError):
                    inspect_references([], ['fixture'], max_seconds=value)
                discover.assert_not_called()
                opened.assert_not_called()

    def test_fractional_time_is_valid_without_granting_clearance(self):
        result = inspect_references([], [], max_seconds=0.5)
        self.assertEqual(result['bytes_read'], 0)
        self.assertEqual(result['dependency_state'], 'UNKNOWN')
        self.assertFalse(result['dependency_clearance'])
