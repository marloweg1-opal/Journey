import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from core import quarantine
from core import journal
from core.apply import undo_apply
from core.recovery_inspection import inspect_operation
from core.shadow import _metadata_probe, run_shadow
from db.database import initialize_schema


class GateAEnforcementTests(unittest.TestCase):
    def test_completion_does_not_advertise_unproven_undo(self):
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        initialize_schema(conn)
        try:
            with patch.object(journal, 'check_kill_switch'), patch('builtins.print') as output:
                op = journal.begin_transaction(conn, {'action_type':'file_move','tier':3,'target_path':'fixture','planned_changes':{}}, {})
                result = journal.complete_operation(conn, op, {}, True)
            self.assertEqual(result['undo_state'], 'UNDO_REQUIRES_REVIEW')
            self.assertFalse(any('Undo available: YES' in str(c) for c in output.call_args_list))
        finally:
            conn.close()

    def test_quarantine_helpers_hold_without_touching_source_or_creating_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/'source'
            source.write_bytes(b'preserve')
            with patch.object(quarantine, 'get_quarantine_root', return_value=Path(tmp)/'absent'):
                self.assertEqual(quarantine.list_quarantine(tmp), [])
                self.assertFalse((Path(tmp)/'absent').exists())
                self.assertEqual(quarantine.quarantine_item(None, str(source), 99)['status'], 'held')
                self.assertEqual(quarantine.restore_from_quarantine(str(source))['status'], 'UNDO_REQUIRES_REVIEW')
            self.assertEqual(source.read_bytes(), b'preserve')

    def test_current_sweep_change_is_distinct_from_ledger_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'item'
            path.write_bytes(b'new')
            info = path.stat()
            live = {'canonical_path':str(path), 'size_bytes':info.st_size, 'mtime_ns':info.st_mtime_ns,
                    'modified_at':time.strftime('%Y-%m-%dT%H:%M:%S',time.localtime(info.st_mtime)), 'evidence_source':'live_scan'}
            ledger = {**live, 'size_bytes':99, 'evidence_source':'both', 'live_observation':live}
            self.assertEqual(_metadata_probe(ledger)[0], 'LEDGER_METADATA_DRIFT')
            path.write_bytes(b'changed after discovery')
            self.assertEqual(_metadata_probe(ledger)[0], 'UNSTABLE_DURING_SCAN')

    def test_shadow_dependency_evidence_is_scoped_and_unknown(self):
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        initialize_schema(conn)
        try:
            with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as reports:
                root = Path(tmp)
                (root/'asset.png').write_bytes(b'fixture')
                (root/'skin.ini').write_text('[Skin]\nImageName=asset.png')
                from core.perception_policy import set_policy
                set_policy(conn, tmp, 'LIMITED', reason='Disposable dependency fixture',
                           purposes=('dependency_inspection',), retention=True)
                result = run_shadow(conn, scope=tmp, docs_root=reports, limit=10)
                self.assertFalse(result['dependency_coverage']['dependency_clearance'])
                rows = conn.execute('SELECT evidence_json FROM stewardship_findings').fetchall()
                evidence = [json.loads(row[0])['dependency_evidence'] for row in rows]
                self.assertTrue(evidence)
                self.assertTrue(all(e['dependency_state']=='UNKNOWN' for e in evidence))
                self.assertTrue(any(e['bounded_references'] for e in evidence))
                (root/'skin.ini').write_text('[Skin]\nImageName=other.png')
                changed = run_shadow(conn, scope=tmp, docs_root=reports, limit=10)
                self.assertGreaterEqual(len(changed['comparison']['changed']), 2)
        finally:
            conn.close()

    def test_shadow_persists_dependency_method_limits(self):
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        initialize_schema(conn)
        try:
            with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as reports:
                root = Path(tmp)
                (root/'asset.png').write_bytes(b'fixture')
                (root/'script.ps1').write_text("$image = 'asset.png'")
                (root/'config.json').write_text('{"image":"asset.png"}')
                from core.perception_policy import set_policy
                set_policy(conn, tmp, 'LIMITED', reason='Disposable method-coverage fixture',
                           purposes=('dependency_inspection',), retention=True)
                result = run_shadow(conn, scope=tmp, docs_root=reports, limit=10)
                persisted = json.loads(conn.execute(
                    'SELECT summary_json FROM shadow_runs WHERE id=?',
                    (result['shadow_run_id'],)).fetchone()[0])
                report = json.loads(Path(result['evidence_path']).read_text(encoding='utf-8'))
                for summary in (result, persisted, report['summary']):
                    coverage = summary['dependency_coverage']
                    checked = {Path(item['path']).name: item for item in coverage['checked']}
                    self.assertEqual(checked['script.ps1']['reference_method'], 'TEXT_MATCHING_ONLY')
                    self.assertFalse(checked['script.ps1']['structured_parser_supported'])
                    self.assertEqual(checked['config.json']['reference_method'],
                                     'STRUCTURED_LITERALS_AND_TEXT_MATCHING')
                    self.assertTrue(checked['config.json']['structured_parser_supported'])
                    self.assertTrue(all(not item['dependency_semantics_complete']
                                        for item in checked.values()))
                    self.assertEqual(coverage['dependency_state'], 'UNKNOWN')
                    self.assertFalse(coverage['dependency_clearance'])
                self.assertEqual(result['managed_file_mutations'], 0)
        finally:
            conn.close()

    def test_corrupt_receipts_require_recovery(self):
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        initialize_schema(conn)
        try:
            for value in ('{broken', '[]', 'null', '42'):
                cur = conn.execute("INSERT INTO action_log(action_type,tier,previous_state,new_state,status) VALUES('file_move',3,?,'{}','applied')", (value,))
                self.assertEqual(inspect_operation(conn, cur.lastrowid)['state'], 'MANUAL_RECOVERY_REQUIRED')
        finally:
            conn.close()

    def test_legacy_shortcut_undo_does_not_delete_a_replacement(self):
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        initialize_schema(conn)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                occupant = Path(tmp)/'replacement'
                occupant.mkdir()
                cur = conn.execute("INSERT INTO action_log(action_type,tier,previous_state,new_state,status) VALUES('file_shortcut',3,?,?, 'applied')",
                    (json.dumps({'path':str(Path(tmp)/'old')}),json.dumps({'path':str(occupant)})))
                self.assertEqual(undo_apply(conn, cur.lastrowid)['status'], 'UNDO_REQUIRES_REVIEW')
                self.assertTrue(occupant.is_dir())
                self.assertEqual(conn.execute('SELECT state FROM operation_recovery_events').fetchone()[0], 'UNDO_REQUIRES_REVIEW')
        finally:
            conn.close()
