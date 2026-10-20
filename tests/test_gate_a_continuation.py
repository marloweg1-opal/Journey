import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core import journal
from dependency_fixture import inspect_references
from core.reference_formats import structured_references
from core.patrol_state import read_state, update_state
from core.retirement_evidence import evaluate_retirement
from db.database import initialize_schema


class GateAContinuationTests(unittest.TestCase):
    def test_relative_configuration_references_and_unicode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / 'asset.png'
            documents = {'skin.ini': '[Skin]\nImageName=asset.png',
                         'config.json': json.dumps({'asset': 'asset.png'}),
                         'config.toml': 'asset="asset.png"',
                         'config.xml': '<skin image="asset.png"/>',
                         'style.css': 'x { background: url("asset.png"); }'}
            for name, text in documents.items():
                (root/name).write_text(text, encoding='utf-16' if name.endswith('.ini') else 'utf-8')
            result = inspect_references([str(target)], [tmp])
            self.assertEqual(len([r for r in result['references'] if r['match'] == 'resolved_literal']), 5)
            self.assertEqual(result['dependency_state'], 'UNKNOWN')
            self.assertFalse(result['dependency_clearance'])

    def test_dynamic_parse_failure_and_binary_are_not_clearance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'skin.ini').write_text('[Skin]\nImageName=#@#Images\\asset.png')
            (root/'bad.json').write_text('{broken')
            (root/'shortcut.lnk').write_bytes(b'unknown binary reference')
            result = inspect_references(['asset.png'], [tmp])
            self.assertTrue(result['errors'])
            literals, _ = structured_references(root/'skin.ini', '[Skin]\nImageName=#@#Images\\asset.png')
            self.assertTrue(any(r['state'] == 'UNRESOLVED_DYNAMIC' for r in literals))
            self.assertEqual(result['structured_candidates'], [])
            self.assertFalse(result['dependency_clearance'])

    def test_retirement_requires_role_not_just_matching_content(self):
        claim = {'fingerprint': 'current', 'receipt': 'fixture', 'source': 'verified_inspector',
                 'condition': 'verified_redundancy', 'retained_copy_receipt': 'copy',
                 'content_comparison_receipt': 'same-bytes'}
        self.assertIn('role_equivalence_receipt', evaluate_retirement(claim, fingerprint='current')['missing'])
        claim['role_equivalence_receipt'] = 'reviewed-role'
        self.assertEqual(evaluate_retirement(claim, fingerprint='current')['state'], 'SUPPORTED_CLAIM')
        self.assertEqual(evaluate_retirement(claim, fingerprint='stale')['state'], 'REVIEW')

    def test_all_retirement_classes_require_affirmative_receipts(self):
        for condition in ('explicit_retirement', 'explicit_supersession', 'verified_residue', 'empty', 'old'):
            with self.subTest(condition=condition):
                self.assertEqual(evaluate_retirement({'condition': condition}, fingerprint='a')['state'], 'REVIEW')

    def test_patrol_survives_reopen_and_rejects_stale_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'state.sqlite'
            with sqlite3.connect(path) as conn:
                initial = read_state(conn)
                changed = update_state(conn, version=initial['version'], paused=True, reason='fixture')
                with self.assertRaises(ValueError):
                    update_state(conn, version=initial['version'], paused=False, reason='stale')
            conn.close()
            with sqlite3.connect(path) as conn:
                self.assertEqual(read_state(conn), changed)
                self.assertEqual(changed['authority'], 'Shadow/explicit approval')
                self.assertEqual(changed['lifecycle'], 'CONSTRUCTION')
            conn.close()

    def test_undo_interruption_has_durable_receipt_and_no_retry(self):
        for after_mutation in (False, True):
            with self.subTest(after_mutation=after_mutation), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)/'journal.sqlite'
                source, dest = Path(tmp)/'source', Path(tmp)/'dest'
                dest.write_bytes(b'fixture original')
                conn = sqlite3.connect(path)
                conn.row_factory = sqlite3.Row
                initialize_schema(conn)
                with patch.object(journal, 'check_kill_switch'), patch('builtins.print'):
                    op = journal.begin_transaction(conn, {'action_type':'file_move','tier':3,'target_path':str(source),'planned_changes':{'dest':str(dest)}}, {'path':str(source)})
                    journal.complete_operation(conn, op, {'path':str(dest)}, True)
                    def interrupted(previous):
                        if after_mutation:
                            dest.rename(source)
                        raise KeyboardInterrupt('fixture interruption')
                    with self.assertRaises(KeyboardInterrupt):
                        journal.undo_operation(conn, op, interrupted)
                conn.close()
                conn = sqlite3.connect(path)
                conn.row_factory = sqlite3.Row
                try:
                    rows = conn.execute('SELECT status FROM action_log').fetchall()
                    self.assertEqual([r[0] for r in rows], ['manual_recovery_required']*2)
                    callback = Mock()
                    with patch.object(journal, 'check_kill_switch'):
                        journal.undo_operation(conn, op, callback)
                    callback.assert_not_called()
                    self.assertEqual((source if after_mutation else dest).read_bytes(), b'fixture original')
                finally:
                    conn.close()

    def test_successful_undo_is_idempotent(self):
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        initialize_schema(conn)
        try:
            with patch.object(journal, 'check_kill_switch'), patch('builtins.print'):
                op = journal.begin_transaction(conn, {'action_type':'fixture','tier':3,'target_path':'fixture','planned_changes':{}}, {})
                journal.complete_operation(conn, op, {}, True)
                callback = Mock()
                journal.undo_operation(conn, op, callback)
                self.assertEqual(journal.undo_operation(conn, op, callback)['status'], 'already_reversed')
                self.assertEqual(callback.call_count, 1)
        finally:
            conn.close()
