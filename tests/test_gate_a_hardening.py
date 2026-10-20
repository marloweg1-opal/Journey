import errno
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import apply, journal
from core.action_evidence import assess_action, REQUIREMENTS
from dependency_fixture import inspect_references
from core.reference_formats import structured_references
from core.recovery_inspection import file_identity
from db.database import initialize_schema
from core.patrol_state import read_state, update_state
from core.shadow import run_shadow


class GateAHardeningTests(unittest.TestCase):
    def test_html_static_references_without_script_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'index.html').write_text('<script src="assets/state.js"></script><img src="assets/photo.png">'
                                          '<a href="javascript:alert(1)">x</a><img src="https://example.invalid/a.png">')
            target = str(root/'assets'/'photo.png')
            result = inspect_references([target], [tmp])
            self.assertTrue(any(r['match']=='resolved_literal' for r in result['references']))
            literals, _ = structured_references(root/'index.html', (root/'index.html').read_text())
            self.assertEqual(len(literals), 2)
            self.assertEqual(result['structured_candidates'], [])
            self.assertFalse(result['dependency_clearance'])

    def test_html_base_and_srcset_remain_uncertain(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'index.html'
            path.write_text('<base href="elsewhere/"><img src="asset.png" srcset="a.png 1x, b.png 2x">')
            result = inspect_references([str(path.parent/'asset.png')], [tmp])
            self.assertTrue(result['errors'])
            self.assertFalse(any(r['match']=='resolved_literal' for r in result['references']))
            self.assertFalse(result['dependency_clearance'])

    def test_direct_shadow_honors_persistent_pause(self):
        conn = sqlite3.connect(':memory:')
        try:
            state = read_state(conn)
            update_state(conn, version=state['version'], paused=True, reason='fixture pause')
            with patch('core.shadow.live_discover') as discover:
                with self.assertRaises(PermissionError):
                    run_shadow(conn, scope='fixture', docs_root='fixture')
            discover.assert_not_called()
        finally:
            conn.close()

    def test_corrupt_or_expanded_patrol_posture_stays_paused(self):
        conn = sqlite3.connect(':memory:')
        try:
            read_state(conn)
            for value in ('{broken', '[]', '{"paused":"false"}',
                          '{"paused":false,"authority":"STEWARD"}'):
                conn.execute('INSERT INTO patrol_control_events(state_json,reason) VALUES(?,?)', (value,'fixture'))
                conn.commit()
                state = read_state(conn)
                self.assertTrue(state['paused'])
                self.assertEqual(state['state_integrity'], 'REVIEW_REQUIRED')
                self.assertEqual(state['authority'], 'Shadow/explicit approval')
        finally:
            conn.close()

    def test_completion_cannot_resurrect_reversed_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn, source, dest = self.fixture(Path(tmp))
            try:
                with patch.object(journal, 'check_kill_switch'), patch('builtins.print'):
                    op = journal.begin_transaction(conn, {'action_type':'fixture','tier':3,
                        'target_path':str(source),'planned_changes':{}}, {})
                    journal.complete_operation(conn, op, {}, True)
                    journal.undo_operation(conn, op, lambda state: None)
                    with self.assertRaises(ValueError):
                        journal.complete_operation(conn, op, {'forged':True}, True)
                self.assertEqual(conn.execute('SELECT status FROM action_log WHERE id=?',(op,)).fetchone()[0], 'reversed')
            finally:
                conn.close()

    def test_malformed_undo_receipt_is_review_not_callback(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn, source, dest = self.fixture(Path(tmp))
            try:
                for value in ('{broken', 'null', '[]'):
                    cur = conn.execute("INSERT INTO action_log(action_type,tier,target_path,previous_state,status) VALUES('fixture',3,?,?,'applied')",(str(source),value))
                    conn.commit()
                    with patch.object(journal,'check_kill_switch'), patch('builtins.print'):
                        with patch.object(apply, '_move_no_replace') as callback:
                            result = journal.undo_operation(conn,cur.lastrowid,callback)
                    callback.assert_not_called()
                    self.assertEqual(result['status'],'MANUAL_RECOVERY_REQUIRED')
                self.assertEqual(source.read_bytes(),b'original')
            finally:
                conn.close()

    def test_truthy_completion_flag_is_not_verification(self):
        conn = sqlite3.connect(':memory:')
        try:
            for value in ('yes', 1, None):
                with self.assertRaises(ValueError):
                    journal.complete_operation(conn, 1, {}, value)
        finally:
            conn.close()

    def test_failed_decoding_consumes_dependency_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('a.json', 'b.json', 'c.json'):
                (root/name).write_bytes(b'\x80'*10)
            result = inspect_references(['missing'], [tmp], max_bytes=20)
            self.assertEqual(result['bytes_read'], 20)
            self.assertFalse(result['dependency_clearance'])
            self.assertTrue(result['errors'])

    def test_dependency_reparse_check_precedes_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'a.json'
            path.write_text('{}')
            with patch('core.dependency_evidence.safe_metadata', side_effect=ValueError('reparse ancestor')):
                with patch.object(Path, 'open') as reader:
                    result = inspect_references(['missing'], [tmp])
            reader.assert_not_called()
            self.assertEqual(result['bytes_read'], 0)
            self.assertEqual(result['dependency_state'], 'UNKNOWN')

    def test_path_drift_read_is_charged_not_trusted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'a.json'
            path.write_text('{}')
            before = path.stat()
            with patch('core.dependency_evidence.safe_metadata', side_effect=[before, ValueError('replaced ancestor')]):
                result = inspect_references(['missing'], [str(path)])
            self.assertEqual(result['bytes_read'], 2)
            self.assertEqual(result['checked'], [])
            self.assertFalse(result['dependency_clearance'])

    def test_invalid_dependency_budgets_rejected(self):
        for key in ('max_files', 'max_bytes', 'max_seconds'):
            with self.assertRaises(ValueError):
                inspect_references([], [], **{key: 0})

    def test_identity_reparse_ancestor_cannot_be_hashed(self):
        with patch('core.media_inventory.safe_metadata', side_effect=ValueError('reparse')):
            with patch.object(Path, 'open') as reader:
                self.assertIsNone(file_identity(Path('fixture')))
        reader.assert_not_called()

    def test_self_asserted_verified_receipts_never_become_high(self):
        for action, kinds in REQUIREMENTS.items():
            facts = [{'kind': kind, 'verified': True, 'receipt': 'invented',
                      'fingerprint': 'current', 'source': 'operator_review',
                      'coverage_complete': True, 'unresolved': 0,
                      'condition': 'explicit_retirement', 'owner_decision_receipt': 'invented'}
                     for kind in kinds]
            for verifier in (None, lambda fact, fingerprint: False,
                             lambda fact, fingerprint: 'truthy-not-proof'):
                result = assess_action(action, facts, current_fingerprint='current', receipt_verifier=verifier)
                self.assertFalse(result['eligible'])
                self.assertNotEqual(result['confidence'], 'HIGH')

    def test_verifier_failure_and_malformed_facts_fail_closed(self):
        facts = [{'kind': kind, 'verified': True, 'receipt': 'claim', 'fingerprint': 'a',
                  'source': 'operator_review', 'coverage_complete': True, 'unresolved': 0}
                 for kind in REQUIREMENTS['MIGRATE']]
        def unavailable(fact, fingerprint):
            raise OSError('receipt store unavailable')
        self.assertFalse(assess_action('MIGRATE', facts + [None], current_fingerprint='a',
                                      receipt_verifier=unavailable)['eligible'])

    def fixture(self, root):
        source, dest = root/'source', root/'dest'
        source.write_bytes(b'original')
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        initialize_schema(conn)
        conn.execute("INSERT INTO proposals(description,status) VALUES('fixture','approved')")
        conn.execute("INSERT INTO proposal_items(proposal_id,canonical_path,dest_path,requested_mode) VALUES(1,?,?,'move')",
                     (str(source), str(dest)))
        conn.commit()
        return conn, source, dest

    def run_apply(self, conn):
        with patch.object(apply, 'move_evidence_hold', return_value=None), patch.object(apply, 'check_operation_magnitude'), patch.object(journal, 'check_kill_switch'), patch('builtins.print'):
            return apply.execute_apply(conn, {'to_apply': [{'item_id':1, 'action':'move'}]}, verbose=False)

    @unittest.skipUnless(os.name == 'nt', 'Windows no-replace primitive')
    def test_destination_race_never_overwrites_or_nests(self):
        for directory in (True, False):
            with tempfile.TemporaryDirectory() as tmp:
                conn, source, dest = self.fixture(Path(tmp))
                try:
                    original_move = apply._move_no_replace
                    def race(src, dst):
                        if directory:
                            dst.mkdir()
                            (dst/'occupant').write_bytes(b'current reality')
                        else:
                            dst.write_bytes(b'current reality')
                        original_move(src, dst)
                    with patch.object(apply, '_move_no_replace', race):
                        result = self.run_apply(conn)
                    self.assertEqual(result['failed_count'], 1)
                    self.assertEqual(source.read_bytes(), b'original')
                    self.assertEqual((dest/'occupant' if directory else dest).read_bytes(), b'current reality')
                    self.assertEqual(conn.execute('SELECT status FROM action_log').fetchone()[0], 'manual_recovery_required')
                finally:
                    conn.close()

    def test_cross_volume_rename_error_never_falls_back_to_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn, source, dest = self.fixture(Path(tmp))
            try:
                with patch.object(apply.os, 'rename', side_effect=OSError(errno.EXDEV, 'fixture cross-volume')):
                    with patch.object(apply.shutil, 'move') as fallback:
                        result = self.run_apply(conn)
                fallback.assert_not_called()
                self.assertEqual(result['failed_count'], 1)
                self.assertEqual(source.read_bytes(), b'original')
                self.assertFalse(dest.exists())
            finally:
                conn.close()

    def test_missing_destination_parent_is_not_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn, source, dest = self.fixture(Path(tmp))
            try:
                missing = Path(tmp)/'missing'/'dest'
                conn.execute('UPDATE proposal_items SET dest_path=?', (str(missing),))
                conn.commit()
                self.assertEqual(self.run_apply(conn)['failed_count'], 1)
                self.assertFalse(missing.parent.exists())
                self.assertEqual(source.read_bytes(), b'original')
                self.assertEqual(conn.execute('SELECT count(*) FROM action_log').fetchone()[0], 0)
            finally:
                conn.close()
