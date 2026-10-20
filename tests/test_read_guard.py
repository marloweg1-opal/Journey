import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.read_guard import evaluate, evaluate_store, require_not_held


class ReadGuardTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.addCleanup(self.conn.close)
        self.conn.execute('CREATE TABLE media_source_holds(scope,reason)')
        self.conn.execute('INSERT INTO media_source_holds VALUES (?,?)', ('F:\\', 'held'))

    def test_denial_has_no_target_io(self):
        with patch('pathlib.Path.stat') as stat, patch('pathlib.Path.open') as opened:
            for path in ('F:\\a', 'f:/a/../b', 'F:\\'):
                with self.assertRaises(PermissionError):
                    require_not_held(self.conn, path)
        stat.assert_not_called()
        opened.assert_not_called()

    def test_scope_boundaries_and_recheck(self):
        self.conn.execute('INSERT INTO media_source_holds VALUES (?,?)', ('R:\\held', 'held'))
        self.assertEqual(evaluate(self.conn, 'R:\\held\\a').state, 'SOURCE_HELD')
        self.assertEqual(evaluate(self.conn, 'R:\\held-other').state, 'NOT_HELD')
        self.conn.execute('INSERT INTO media_source_holds VALUES (?,?)', ('R:\\held-other', 'new'))
        self.assertEqual(evaluate(self.conn, 'R:\\held-other').state, 'SOURCE_HELD')

    def test_malformed_policy_fails_closed(self):
        self.conn.execute('INSERT INTO media_source_holds VALUES (?,?)', ('relative', 'bad'))
        self.assertEqual(evaluate(self.conn, 'R:\\okay').state, 'POLICY_UNAVAILABLE')
        self.conn.execute('DROP TABLE media_source_holds')
        self.assertEqual(evaluate(self.conn, 'R:\\okay').state, 'POLICY_UNAVAILABLE')

    def test_unsupported_paths(self):
        for path in ('relative', 'R:relative', '\\\\?\\F:\\a', '\\\\.\\F:',
                     '\\\\host\\share', 'R:\\a:stream', 'R:\\folder.\\a'):
            with self.subTest(path=path):
                self.assertEqual(evaluate(self.conn, path).state, 'UNSUPPORTED_PATH')

    def test_store_missing_corrupt_and_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / 'holds.sqlite'
            self.assertEqual(evaluate_store(store, 'R:\\a').state, 'POLICY_UNAVAILABLE')
            self.assertFalse(store.exists())
            store.write_bytes(b'not sqlite')
            self.assertEqual(evaluate_store(store, 'R:\\a').state, 'POLICY_UNAVAILABLE')
            store.unlink()
            conn = sqlite3.connect(store)
            self.conn.commit()
            self.conn.backup(conn)
            conn.close()
            self.assertEqual(evaluate_store(store, 'F:\\a').state, 'SOURCE_HELD')
