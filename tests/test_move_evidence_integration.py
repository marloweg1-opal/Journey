import json
import sqlite3
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from core import apply, journal
from core.move_evidence import (MoveEvidence, MoveEvidenceVerifier, MoveIdentity,
                                approval_binding)
from core.recovery_inspection import file_identity
from db.database import initialize_schema


class FixtureVerifier(MoveEvidenceVerifier):
    """Test-only issuer for exact files created by this disposable fixture."""
    def __init__(self, evidence):
        self.evidence = evidence
        self.deny_phase = None

    def verify(self, conn, item, *, phase):
        if phase == self.deny_phase:
            raise ValueError('fixture revocation')
        return self.evidence


class MoveEvidenceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'fixture-source.png'
        self.dest = self.root / 'fixture-custody.png'
        self.source.write_bytes(b'disposable CareBloom custody fixture')
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        initialize_schema(self.conn)
        self.conn.execute("INSERT INTO proposals(description,status) VALUES('fixture','approved')")
        self.conn.execute("INSERT INTO proposal_items(proposal_id,canonical_path,dest_path,requested_mode) VALUES(1,?,?,'move')",
                          (str(self.source), str(self.dest)))
        self.conn.commit()
        identity = file_identity(self.source)
        self.assertIsNotNone(identity)
        proposal = self.conn.execute('SELECT * FROM proposals WHERE id=1').fetchone()
        self.evidence = MoveEvidence(
            receipt_id='fixture-receipt', approval_reference='fixture-explicit-approval',
            approval_binding=approval_binding(proposal),
            evidence_references=('fixture-created-by-test-no-external-consumers',),
            proposal_id=1, item_id=1, source=str(self.source), destination=str(self.dest),
            source_scope=str(self.root), destination_scope=str(self.root),
            identity=MoveIdentity(**identity), issued_at=time.time()-1, expires_at=time.time()+60)
        self.verifier = FixtureVerifier(self.evidence)
        # Isolate unrelated global fixture controls; do not patch the evidence gate.
        for mocked in (patch.object(apply, 'check_operation_magnitude'),
                       patch.object(journal, 'KILL_SWITCH_FLAG', self.root/'stop.flag'),
                       patch('builtins.print')):
            mocked.start()
            self.addCleanup(mocked.stop)

    def execute(self):
        return apply.execute_apply(self.conn, {'to_apply':[{'item_id':1,'action':'move'}]},
                                   verbose=False, move_verifier=self.verifier)

    def assert_untouched(self):
        self.assertEqual(self.source.read_bytes(), b'disposable CareBloom custody fixture')
        self.assertFalse(self.dest.exists())

    def test_exact_fixture_moves_with_bound_intent_and_undo(self):
        plan = apply.plan_apply(self.conn, 1, move_verifier=self.verifier)
        self.assertEqual(len(plan['to_apply']), 1)
        original_move = apply._move_no_replace
        def inspect_intent(source, dest):
            row = self.conn.execute('SELECT * FROM action_log').fetchone()
            previous = json.loads(row['previous_state'])
            self.assertEqual(previous['move_evidence']['receipt_id'], 'fixture-receipt')
            self.assertEqual(previous['move_evidence']['identity'], file_identity(source))
            self.assertEqual(self.conn.execute('SELECT action_log_id FROM proposal_items').fetchone()[0], row['id'])
            original_move(source, dest)
        with patch.object(apply, '_move_no_replace', side_effect=inspect_intent):
            result = self.execute()
        self.assertEqual(result['applied_count'], 1)
        self.assertFalse(self.source.exists())
        self.assertEqual(self.dest.read_bytes(), b'disposable CareBloom custody fixture')
        self.assertEqual(apply.undo_apply(self.conn, result['applied'][0]['op_id'])['status'], 'reversed')
        self.assert_untouched()

    def test_plan_fields_cannot_install_verifier_or_clearance(self):
        result = apply.execute_apply(self.conn, {'move_verifier':self.verifier,
            'to_apply':[{'item_id':1,'action':'move','verified':True,'dependency_clearance':True}]}, verbose=False)
        self.assertEqual(result['applied_count'], 0)
        self.assert_untouched()

    def test_invalid_bindings_and_windows_fail_before_filesystem_probe(self):
        cases = [replace(self.evidence, item_id=2), replace(self.evidence, proposal_id=2),
                 replace(self.evidence, destination=str(self.root/'elsewhere')),
                 replace(self.evidence, source_scope=str(self.root/'other')),
                 replace(self.evidence, destination_scope=str(self.root/'other')),
                 replace(self.evidence, approval_binding='wrong'),
                 replace(self.evidence, evidence_references=()),
                 replace(self.evidence, expires_at=time.time()-2),
                 replace(self.evidence, expires_at=float('nan')),
                 replace(self.evidence, issued_at=time.time()+30), True, {'verified':True}]
        for evidence in cases:
            with self.subTest(evidence=evidence):
                self.verifier.evidence = evidence
                with patch.object(apply.os.path, 'lexists') as probe:
                    self.assertEqual(self.execute()['applied_count'], 0)
                probe.assert_not_called()
        self.assert_untouched()

    def test_revocation_before_intent_and_after_intent(self):
        for phase in ('execute', 'before_intent', 'before_mutation'):
            with self.subTest(phase=phase):
                self.verifier.deny_phase = phase
                result = self.execute()
                self.assertEqual(result['applied_count'], 0)
                self.assert_untouched()
                row = self.conn.execute('SELECT * FROM action_log').fetchone()
                if phase == 'before_mutation':
                    self.assertEqual(row['status'], 'manual_recovery_required')
                    self.assertIn('fixture-receipt', row['previous_state'])
                else:
                    self.assertIsNone(row)

    def test_source_and_approval_drift_deny(self):
        self.conn.execute("UPDATE proposals SET description='changed approval scope'")
        self.conn.commit()
        self.assertEqual(self.execute()['applied_count'], 0)
        self.conn.execute("UPDATE proposals SET description='fixture'")
        self.conn.commit()
        self.source.write_bytes(b'new occupant content')
        self.assertEqual(self.execute()['applied_count'], 0)
        self.assertEqual(self.source.read_bytes(), b'new occupant content')
        self.assertFalse(self.dest.exists())

    def test_occupied_destination_never_modified(self):
        self.dest.write_bytes(b'occupant')
        self.assertEqual(self.execute()['applied_count'], 0)
        self.assertEqual(self.dest.read_bytes(), b'occupant')
        self.assertTrue(self.source.exists())

    def test_current_holds_still_override_fixture_evidence(self):
        (self.root/'stop.flag').touch()
        self.assertEqual(self.execute()['status'], 'blocked_by_kill_switch')
        self.assert_untouched()

    def test_dependency_and_source_hold_override_evidence(self):
        apply.register_dependent(self.conn, str(self.source), 'fixture consumer')
        self.assertEqual(self.execute()['applied_count'], 0)
        self.assert_untouched()
        self.conn.execute('DELETE FROM file_dependents')
        self.conn.commit()
        with patch('core.read_guard.require_path_not_held', side_effect=ValueError('fixture hold')):
            self.assertEqual(self.execute()['applied_count'], 0)
        self.assert_untouched()

    def test_interrupted_move_keeps_bound_intent_and_blocks_replay(self):
        def interrupted(source, dest):
            apply.os.rename(source, dest)
            raise OSError('fixture interruption after rename')
        with patch.object(apply, '_move_no_replace', side_effect=interrupted):
            self.assertEqual(self.execute()['applied_count'], 0)
        row = self.conn.execute('SELECT * FROM action_log').fetchone()
        self.assertEqual(row['status'], 'manual_recovery_required')
        self.assertEqual(json.loads(row['previous_state'])['move_evidence']['receipt_id'], 'fixture-receipt')
        self.assertEqual(self.conn.execute('SELECT action_log_id FROM proposal_items').fetchone()[0], row['id'])
        self.assertEqual(self.execute()['applied_count'], 0)
        self.assertFalse(self.source.exists())
        self.assertEqual(self.dest.read_bytes(), b'disposable CareBloom custody fixture')

    def test_undo_preserves_reoccupied_source_and_replay_is_blocked(self):
        result = self.execute()
        self.assertEqual(result['applied_count'], 1)
        self.source.write_bytes(b'new occupant')
        undo = apply.undo_apply(self.conn, result['applied'][0]['op_id'])
        self.assertEqual(undo['status'], 'UNDO_BLOCKED_BY_DRIFT')
        self.assertEqual(self.execute()['applied_count'], 0)
        self.assertEqual(self.source.read_bytes(), b'new occupant')
        self.assertEqual(self.dest.read_bytes(), b'disposable CareBloom custody fixture')
