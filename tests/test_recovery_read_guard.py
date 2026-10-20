import sqlite3
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.read_guard import evaluate_store
from core.recovery_inspection import file_identity, path_evidence, inspect_operation


class RecoveryReadGuardTests(unittest.TestCase):
    def test_receipt_denial_never_advertises_undo(self):
        conn = sqlite3.connect(':memory:')
        self.addCleanup(conn.close)
        conn.row_factory = sqlite3.Row
        conn.execute('CREATE TABLE action_log(id, previous_state, new_state, status, action_type)')
        conn.execute('INSERT INTO action_log VALUES(?,?,?,?,?)', (
            1, json.dumps({'path': 'F:\\original'}),
            json.dumps({'path': 'F:\\moved', 'identity': {'sha256': 'fixture'}}),
            'applied', 'file_move'))
        with patch('core.recovery_inspection.require_path_not_held',
                   side_effect=PermissionError('SOURCE_HELD')), patch('pathlib.Path.lstat') as stat:
            result = inspect_operation(conn, 1)
        self.assertEqual(result['state'], 'UNDO_REQUIRES_REVIEW')
        self.assertEqual(result['source']['state'], 'UNKNOWN')
        self.assertEqual(result['destination']['state'], 'UNKNOWN')
        stat.assert_not_called()

    def test_denial_precedes_ancestor_probes_and_open(self):
        for reason in ('SOURCE_HELD', 'POLICY_UNAVAILABLE', 'UNSUPPORTED_PATH'):
            with self.subTest(reason=reason), patch(
                'core.recovery_inspection.require_path_not_held',
                side_effect=PermissionError(reason)
            ), patch('pathlib.Path.lstat') as stat, patch('pathlib.Path.open') as opened:
                self.assertIsNone(file_identity('F:\\fixture'))
                result = path_evidence('F:\\fixture')
                self.assertEqual(result['state'], 'UNKNOWN')
                self.assertIn(reason, result['error'])
                stat.assert_not_called()
                opened.assert_not_called()

    def test_isolated_policy_allows_fixture_and_missing_stays_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = root / 'policy.sqlite'
            conn = sqlite3.connect(store)
            conn.execute('CREATE TABLE media_source_holds(scope,reason)')
            conn.close()
            source = root / 'fixture.bin'
            source.write_bytes(b'fixture')

            def guard(path):
                decision = evaluate_store(store, path)
                if decision.state != 'NOT_HELD':
                    raise PermissionError(decision.state)

            with patch('core.recovery_inspection.require_path_not_held', side_effect=guard):
                self.assertEqual(file_identity(source)['size'], 7)
                self.assertEqual(path_evidence(source)['state'], 'PRESENT')
                store.unlink()
                self.assertIsNone(file_identity(source))
                self.assertEqual(path_evidence(source)['state'], 'UNKNOWN')

    def test_hold_before_open_blocks_content_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'fixture.bin'
            source.write_bytes(b'fixture')
            from core.media_inventory import safe_metadata
            info = safe_metadata(source)
            with patch('core.media_inventory.safe_metadata', return_value=info), patch(
                'core.recovery_inspection.require_path_not_held',
                side_effect=PermissionError('SOURCE_HELD')
            ), patch('pathlib.Path.open') as opened:
                self.assertIsNone(file_identity(source))
                opened.assert_not_called()
