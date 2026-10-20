import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.media_inventory import hold_source, register, batch, hash_batch, summary


class SourceHoldTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / 'ledger.sqlite'
        self.conn = sqlite3.connect(self.db)

    def tearDown(self):
        self.conn.close()

    def test_registration_blocked_before_any_source_probe_after_restart(self):
        hold_source(self.conn, 'F:\\', 'storage incident')
        self.conn.close()
        self.conn = sqlite3.connect(self.db)
        with patch('core.media_inventory.safe_metadata') as probe:
            for path in ('F:\\Recovery', 'f:/Recovery/../Other', 'F:\\'):
                with self.assertRaises(PermissionError):
                    register(self.conn, [path])
        probe.assert_not_called()
        self.assertEqual(len(summary(self.conn)['source_holds']), 1)

    def test_already_queued_work_held_without_scan(self):
        register(self.conn, [self.root])
        hold_source(self.conn, str(self.root), 'fixture incident')
        with patch('core.media_inventory.safe_metadata') as probe:
            with patch('core.media_inventory.os.scandir') as scan:
                result = batch(self.conn)
        probe.assert_not_called()
        scan.assert_not_called()
        self.assertEqual(result['directory_states'], {'HELD': 1})
        self.assertEqual(batch(self.conn)['directories_processed_this_batch'], 0)

    def test_previously_inventoried_file_held_before_hash(self):
        (self.root / 'image.png').write_bytes(b'fixture')
        register(self.conn, [self.root])
        batch(self.conn)
        hold_source(self.conn, str(self.root), 'fixture incident')
        with patch('core.media_inventory.safe_metadata') as probe:
            with patch('core.media_inventory.stable_hash') as reader:
                result = hash_batch(self.conn)
        probe.assert_not_called()
        reader.assert_not_called()
        self.assertEqual(result['hash_states'], {'SOURCE_HELD': 1})

    def test_unrelated_source_continues(self):
        hold_source(self.conn, 'F:\\', 'incident')
        (self.root / 'image.png').write_bytes(b'fixture')
        register(self.conn, [self.root])
        self.assertEqual(batch(self.conn)['media_occurrences'], 1)
        self.assertEqual(hash_batch(self.conn)['hash_states'], {'HASHED': 1})

    def test_hold_arriving_between_hashes_blocks_remaining_work(self):
        from core.media_inventory import stable_hash
        (self.root / 'first.png').write_bytes(b'fixture one')
        (self.root / 'second.png').write_bytes(b'fixture two')
        register(self.conn, [self.root])
        batch(self.conn)

        def hash_then_hold(path, **budgets):
            evidence = stable_hash(path, **budgets)
            hold_source(self.conn, str(self.root), 'hold received during batch')
            return evidence

        with patch('core.media_inventory.stable_hash', side_effect=hash_then_hold) as reader:
            result = hash_batch(self.conn)
        self.assertEqual(reader.call_count, 1)
        self.assertEqual(result['hash_states'], {'HASHED': 1, 'SOURCE_HELD': 1})
        self.conn.close()
        self.conn = sqlite3.connect(self.db)
        with patch('core.media_inventory.stable_hash') as reader:
            repeat = hash_batch(self.conn)
        reader.assert_not_called()
        self.assertEqual(repeat['hash_attempts_this_batch'], 0)

    def test_device_alias_rejected_without_probe(self):
        hold_source(self.conn, 'F:\\', 'incident')
        with patch('core.media_inventory.safe_metadata') as probe:
            for path in ('\\\\?\\F:\\Recovery', '\\\\.\\F:\\Recovery'):
                with self.assertRaises(ValueError):
                    register(self.conn, [path])
        probe.assert_not_called()

    def test_nested_hold_does_not_capture_similarly_named_sibling(self):
        blocked = self.root / 'held'
        allowed = self.root / 'held-other'
        blocked.mkdir()
        allowed.mkdir()
        (blocked / 'image.png').write_bytes(b'blocked fixture')
        (allowed / 'image.png').write_bytes(b'allowed fixture')
        hold_source(self.conn, str(blocked), 'nested hold')
        register(self.conn, [self.root])
        result = batch(self.conn)
        self.assertEqual(result['media_occurrences'], 1)
        self.assertEqual(result['directory_states']['HELD'], 1)
        self.assertFalse(result['coverage_complete'])
