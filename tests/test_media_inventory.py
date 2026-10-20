import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.media_inventory import register, batch, summary, hash_batch


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)/'source'
        self.root.mkdir()
        self.db = Path(self.tmp.name)/'inventory.sqlite'
        self.conn = sqlite3.connect(self.db)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def test_resume_survives_restart_without_repeating_completed_directory(self):
        for name in ('a','b'):
            directory = self.root/name
            directory.mkdir()
            (directory/'photo.png').write_bytes(b'fixture')
        register(self.conn,[self.root])
        first = batch(self.conn,max_directories=1)
        self.assertEqual(first['directory_states']['PENDING'],2)
        self.conn.close()
        self.conn = sqlite3.connect(self.db)
        register(self.conn,[self.root])
        result = batch(self.conn)
        self.assertEqual(result['media_occurrences'],2)
        self.assertTrue(result['coverage_complete'])
        self.assertEqual(batch(self.conn)['directories_processed_this_batch'],0)

    def test_interrupted_checkpoint_rolls_back_cursor_and_occurrences(self):
        source = self.root/'photo.png'
        source.write_bytes(b'unchanged')
        register(self.conn,[self.root])
        def interrupt():
            raise RuntimeError('disposable interruption')
        with self.assertRaises(RuntimeError):
            batch(self.conn,checkpoint=interrupt)
        self.assertEqual(summary(self.conn)['media_occurrences'],0)
        self.assertEqual(summary(self.conn)['directory_states'],{'PENDING':1})
        self.assertEqual(batch(self.conn)['media_occurrences'],1)
        self.assertEqual(source.read_bytes(),b'unchanged')

    def test_unreadable_directory_is_held_not_retried(self):
        register(self.conn,[self.root])
        with patch('core.media_inventory.os.scandir',side_effect=PermissionError('fixture inaccessible')):
            result = batch(self.conn)
        self.assertFalse(result['coverage_complete'])
        self.assertEqual(result['estimated_human_decisions'],1)
        self.assertEqual(batch(self.conn)['directories_processed_this_batch'],0)

    def test_budget_does_not_claim_partial_directory_complete(self):
        for name in ('a.png','b.png'):
            (self.root/name).write_bytes(b'fixture')
        register(self.conn,[self.root])
        result = batch(self.conn,max_entries=1)
        self.assertEqual(result['directory_states'],{'HELD':1})
        self.assertEqual(result['media_occurrences'],0)

    def test_directory_drift_requires_review(self):
        register(self.conn,[self.root])
        with patch('core.media_inventory.signature',side_effect=[('after',),('before',)]):
            result = batch(self.conn)
        self.assertFalse(result['coverage_complete'])
        self.assertIn('changed',result['held'][0]['evidence'])

    def test_hash_batches_advance_and_hold_changed_sources(self):
        a,b = self.root/'a.png',self.root/'b.png'
        a.write_bytes(b'first')
        b.write_bytes(b'second')
        register(self.conn,[self.root])
        batch(self.conn)
        first = hash_batch(self.conn,max_files=1)
        self.assertEqual(first['hash_states'],{'HASHED':1})
        remaining = self.conn.execute('''SELECT f.path FROM media_inventory_files f
            LEFT JOIN media_inventory_hashes h ON f.path=h.path WHERE h.path IS NULL''').fetchone()[0]
        Path(remaining).write_bytes(b'changed by fixture')
        result = hash_batch(self.conn)
        self.assertEqual(result['hash_states'],{'CHANGED_SINCE_INVENTORY':1,'HASHED':1})
        self.assertEqual(hash_batch(self.conn)['hash_attempts_this_batch'],0)

    def test_hash_budget_holds_are_not_silent_retries(self):
        (self.root/'large.png').write_bytes(b'large fixture')
        register(self.conn,[self.root])
        batch(self.conn)
        self.assertEqual(hash_batch(self.conn,max_file_bytes=2)['hash_states'],{'BUDGET_HELD':1})
        self.assertEqual(hash_batch(self.conn)['hash_attempts_this_batch'],0)

    def test_hash_reparse_ancestor_is_held_before_content_read(self):
        (self.root/'a.png').write_bytes(b'fixture')
        register(self.conn,[self.root])
        batch(self.conn)
        with patch('core.media_inventory.safe_metadata',side_effect=ValueError('reparse')):
            with patch('core.media_inventory.stable_hash') as reader:
                result = hash_batch(self.conn)
        reader.assert_not_called()
        self.assertEqual(result['hash_states'],{'HELD':1})

    def test_bridge_uses_registered_work_not_payload_scopes(self):
        import mini_ark_server as server
        ledger = Path(self.tmp.name)/'private'/'media_recovery'/'inventory-v2.sqlite'
        ledger.parent.mkdir(parents=True)
        ledger.touch()
        with patch.object(server,'ROOT',Path(self.tmp.name)):
            with patch.object(server,'_run_command',return_value={'ok':True}) as runner:
                result,status = server.run_action('media-inventory-resume',{'roots':['F:\\'], 'max_seconds':99999})
        self.assertEqual(status,200)
        self.assertTrue(result['ok'])
        self.assertNotIn('F:\\',runner.call_args.args[0])
        self.assertNotIn('99999',runner.call_args.args[0])
