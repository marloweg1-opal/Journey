import sqlite3
import unittest
from unittest.mock import patch

from core import apply
from db.database import initialize_schema


class MoveEvidenceHoldTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        initialize_schema(self.conn)
        self.conn.execute("INSERT INTO proposals(description,status) VALUES('fixture','approved')")
        self.conn.execute("INSERT INTO proposal_items(proposal_id,canonical_path,dest_path,requested_mode) VALUES(1,'C:\\fixture-source','C:\\fixture-dest','move')")
        self.conn.commit()

    def test_approved_move_without_dependencies_is_not_clearance(self):
        plan = apply.plan_apply(self.conn, 1)
        self.assertEqual(plan['to_apply'], [])
        self.assertIn('MOVE_EVIDENCE_REQUIRED', plan['blocked'][0]['reason'])

    def test_direct_execution_and_forged_clearance_stop_before_filesystem(self):
        plan = {'to_apply': [{'item_id': 1, 'action': 'move',
                             'dependency_clearance': True, 'verified': True}]}
        with patch.object(apply, 'check_operation_magnitude'), \
                patch.object(apply.os.path, 'lexists') as probe, \
                patch.object(apply, 'file_identity') as identity, \
                patch.object(apply.journal, 'begin_transaction') as begin:
            result = apply.execute_apply(self.conn, plan, verbose=False)
        self.assertEqual(result['applied_count'], 0)
        self.assertEqual(result['failed_count'], 1)
        self.assertIn('MOVE_EVIDENCE_REQUIRED', result['failed'][0]['reason'])
        probe.assert_not_called()
        identity.assert_not_called()
        begin.assert_not_called()
        self.assertEqual(self.conn.execute('SELECT count(*) FROM action_log').fetchone()[0], 0)
