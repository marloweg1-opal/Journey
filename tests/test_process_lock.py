import argparse
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.process_lock import process_lock, ProcessBusyError


class ProcessLockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'inventory.lock'

    def child(self, body):
        return subprocess.run([sys.executable, '-B', '-c',
            'from core.process_lock import process_lock, ProcessBusyError\n'
            'import sys, os\np=sys.argv[1]\n' + body, str(self.path)],
            capture_output=True, text=True, timeout=10)

    def test_competing_process_cannot_enter(self):
        with process_lock(self.path):
            result = self.child('try:\n with process_lock(p): sys.exit(9)\n'
                                'except ProcessBusyError: sys.exit(0)\n')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_abrupt_exit_releases_os_lock(self):
        result = self.child('with process_lock(p): os._exit(23)\n')
        self.assertEqual(result.returncode, 23, result.stderr)
        with process_lock(self.path):
            pass

    def test_exception_releases_lock_without_deleting_file(self):
        with self.assertRaises(RuntimeError):
            with process_lock(self.path):
                raise RuntimeError('fixture interruption')
        self.assertTrue(self.path.exists())
        with process_lock(self.path):
            pass

    def test_continuation_busy_does_not_open_ledger_or_read_sources(self):
        from work import resume_media_inventory as runner
        folder = Path(self.tmp.name) / 'private' / 'media_recovery'
        folder.mkdir(parents=True)
        with process_lock(folder / 'inventory.lock'):
            with patch.object(runner, 'ROOT', Path(self.tmp.name)):
                with patch.object(sys, 'argv', ['resume_media_inventory.py']):
                    with patch.object(runner, 'continue_inventory') as work:
                        self.assertEqual(runner.main(), 2)
        work.assert_not_called()
        self.assertFalse((folder / 'inventory-v2.sqlite').exists())

    def test_checkpointed_batch_can_repeat_after_summary_failure(self):
        from work.resume_media_inventory import continue_inventory
        root = Path(self.tmp.name) / 'source'
        root.mkdir()
        (root / 'fixture.png').write_bytes(b'fixture')
        args = argparse.Namespace(roots=[str(root)], max_directories=10, max_seconds=5, hash_files=10)
        with process_lock(self.path):
            with patch('work.resume_media_inventory.os.replace', side_effect=OSError('fixture interruption')):
                with self.assertRaises(OSError):
                    continue_inventory(Path(self.tmp.name), args)
        with process_lock(self.path):
            result = continue_inventory(Path(self.tmp.name), args)
        self.assertEqual(result['media_occurrences'], 1)
        self.assertEqual(result['hash_states'], {'HASHED': 1})
        self.assertEqual(result['hash_attempts_this_batch'], 0)
