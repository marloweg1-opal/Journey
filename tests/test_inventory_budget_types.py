import sqlite3
import unittest
from unittest.mock import patch

from core import media_inventory as inventory


class InventoryBudgetTypeTests(unittest.TestCase):
    def test_invalid_count_and_byte_limits_stop_before_initialization(self):
        for function, names in ((inventory.batch, ('max_directories', 'max_entries')),
                                (inventory.hash_batch, ('max_files', 'max_bytes', 'max_file_bytes'))):
            for name in names:
                for value in (True, False, 0, -1, 1.5, '10', None, float('inf'), float('nan')):
                    with self.subTest(function=function.__name__, name=name, value=value), \
                            patch.object(inventory, 'initialize') as initialize:
                        with self.assertRaises(ValueError):
                            function(None, **{name: value})
                        initialize.assert_not_called()

    def test_invalid_time_limits_stop_before_initialization(self):
        for function in (inventory.batch, inventory.hash_batch):
            for value in (True, False, 0, -1, '10', None, float('inf'), float('-inf'), float('nan'), 10 ** 500):
                with self.subTest(function=function.__name__, value=value), \
                        patch.object(inventory, 'initialize') as initialize:
                    with self.assertRaises(ValueError):
                        function(None, max_seconds=value)
                    initialize.assert_not_called()

    def test_positive_fractional_time_keeps_empty_fixture_usable(self):
        conn = sqlite3.connect(':memory:')
        self.addCleanup(conn.close)
        self.assertEqual(inventory.batch(conn, max_seconds=0.5)['directories_processed_this_batch'], 0)
        self.assertEqual(inventory.hash_batch(conn, max_seconds=0.5)['hash_attempts_this_batch'], 0)
