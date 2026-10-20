import json
import errno
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import apply, journal
from core.recovery_inspection import inspect_operation
from db.database import initialize_schema


class RecoveryBoundaries(unittest.TestCase):
    def fixture(self, root):
        (root/'DISPOSABLE_GATE_A_FIXTURE').touch()
        (root/'source').write_bytes(b'original fixture content')
        conn = sqlite3.connect(root/'fixture.sqlite')
        conn.row_factory = sqlite3.Row
        initialize_schema(conn)
        conn.execute("INSERT INTO proposals(description,status) VALUES('fixture','approved')")
        conn.execute("INSERT INTO proposal_items(proposal_id,canonical_path,dest_path,requested_mode) VALUES(1,?,?,'move')",
                     (str(root/'source'), str(root/'dest')))
        conn.commit()
        return conn

    def test_process_death_across_copy_delete_and_journal_boundaries(self):
        cases = [('simulated', boundary) for boundary in ('intent_committed', 'partial_copy', 'copy_complete', 'source_removed',
                         'before_verification_receipt', 'verification_committed', 'completed')]
        cases += [('native', boundary) for boundary in ('intent_committed', 'source_removed',
                         'before_verification_receipt', 'verification_committed', 'completed')]
        for mode, boundary in cases:
            with self.subTest(mode=mode, boundary=boundary), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.fixture(root).close()
                worker = Path(__file__).with_name('recovery_fixture_worker.py')
                child = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(worker), tmp, boundary, mode], capture_output=True, timeout=20)
                self.assertEqual(child.returncode, 0 if boundary == 'completed' else 73, child.stderr.decode())
                conn = sqlite3.connect(root/'fixture.sqlite')
                conn.row_factory = sqlite3.Row
                try:
                    item = conn.execute('SELECT * FROM proposal_items').fetchone()
                    receipt = conn.execute('SELECT * FROM action_log').fetchone()
                    self.assertEqual(item['action_log_id'], receipt['id'])
                    inspection = inspect_operation(conn, receipt['id'])
                    self.assertFalse(inspection['automatic_replay'])
                    if boundary not in ('verification_committed', 'completed'):
                        self.assertEqual(inspection['state'], 'MANUAL_RECOVERY_REQUIRED')
                    self.assertEqual(json.loads(receipt['previous_state'])['planned_changes']['dest'], str(root/'dest'))
                    before = {p.name:p.read_bytes() for p in (root/'source',root/'dest') if p.exists()}
                    self.assertIn(b'original fixture content', before.values())
                    with patch.object(apply, 'check_operation_magnitude'), patch.object(apply, '_move_no_replace') as move:
                        result = apply.execute_apply(conn, {'to_apply':[{'item_id':1,'action':'move'}]}, verbose=False)
                    move.assert_not_called()
                    self.assertEqual(result['failed_count'], 1)
                    self.assertEqual(before, {p.name:p.read_bytes() for p in (root/'source',root/'dest') if p.exists()})
                finally:
                    conn.close()

    def test_occupied_undo_preserves_file_or_directory_and_records_conflict(self):
        for directory in (False, True):
            with self.subTest(directory=directory), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                conn = self.fixture(root)
                try:
                    with patch.object(apply, 'move_evidence_hold', return_value=None), patch.object(apply, 'check_operation_magnitude'), patch.object(journal, 'check_kill_switch'), patch('builtins.print'):
                        result = apply.execute_apply(conn, {'to_apply':[{'item_id':1,'action':'move'}]}, verbose=False)
                        self.assertEqual(result['applied_count'], 1)
                        original = root/'source'
                        if directory:
                            original.mkdir()
                            occupant = original/'new-owner'
                        else:
                            occupant = original
                        occupant.write_bytes(b'new unrelated occupant')
                        before = occupant.stat()
                        undo = apply.undo_apply(conn, result['applied'][0]['op_id'])
                    self.assertEqual(undo['status'], 'UNDO_BLOCKED_BY_DRIFT')
                    self.assertEqual(occupant.read_bytes(), b'new unrelated occupant')
                    self.assertEqual(occupant.stat().st_mtime_ns, before.st_mtime_ns)
                    self.assertEqual((root/'dest').read_bytes(), b'original fixture content')
                    event = conn.execute('SELECT * FROM operation_recovery_events').fetchone()
                    self.assertEqual(event['state'], 'UNDO_BLOCKED_BY_DRIFT')
                    self.assertFalse(json.loads(event['evidence_json'])['physical_changes'])
                finally:
                    conn.close()

    def test_claim_failure_rolls_back_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = self.fixture(Path(tmp))
            try:
                conn.execute("UPDATE proposals SET status='superseded'")
                conn.commit()
                with patch.object(journal, 'check_kill_switch'), self.assertRaises(ValueError):
                    journal.begin_transaction(conn, {'action_type':'file_move','tier':3,'target_path':'fixture','planned_changes':{}}, {}, proposal_item_id=1)
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM action_log').fetchone()[0], 0)
            finally:
                conn.close()

    def test_undo_content_drift_and_cross_volume_failure_preserve_reality(self):
        for mode in ('content_drift', 'cross_volume', 'destination_race', 'success'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                conn = self.fixture(root)
                try:
                    with patch.object(apply, 'move_evidence_hold', return_value=None), patch.object(apply, 'check_operation_magnitude'), patch.object(journal, 'check_kill_switch'), patch('builtins.print'):
                        result = apply.execute_apply(conn, {'to_apply':[{'item_id':1,'action':'move'}]}, verbose=False)
                        op = result['applied'][0]['op_id']
                        if mode == 'content_drift':
                            (root/'dest').write_bytes(b'new version')
                            self.assertEqual(apply.undo_apply(conn, op)['status'], 'UNDO_BLOCKED_BY_DRIFT')
                            self.assertEqual((root/'dest').read_bytes(), b'new version')
                        elif mode == 'cross_volume':
                            with patch.object(apply.os, 'rename', side_effect=OSError(errno.EXDEV, 'fixture cross-volume')), self.assertRaises(OSError):
                                apply.undo_apply(conn, op)
                            self.assertEqual(inspect_operation(conn, op)['state'], 'MANUAL_RECOVERY_REQUIRED')
                            self.assertEqual((root/'dest').read_bytes(), b'original fixture content')
                        elif mode == 'destination_race':
                            def occupied(source, dest):
                                Path(dest).write_bytes(b'new occupant')
                                raise FileExistsError('fixture race')
                            with patch.object(apply.os, 'rename', side_effect=occupied):
                                self.assertEqual(apply.undo_apply(conn, op)['status'], 'UNDO_BLOCKED_BY_DRIFT')
                            self.assertEqual((root/'source').read_bytes(), b'new occupant')
                            self.assertEqual((root/'dest').read_bytes(), b'original fixture content')
                        else:
                            self.assertEqual(apply.undo_apply(conn, op)['status'], 'reversed')
                            self.assertEqual(inspect_operation(conn, op)['state'], 'UNDO_COMPLETED')
                            self.assertEqual((root/'source').read_bytes(), b'original fixture content')
                            self.assertFalse((root/'dest').exists())
                finally:
                    conn.close()
