import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import ark


class CliFailureConnectionTests(unittest.TestCase):
    def test_apply_known_failure_exits_close_connection(self):
        plan = {'status': 'planned', 'total_items': 1, 'blocked_count': 0,
                'blocked': [], 'downgraded_count': 0, 'to_apply': [{}]}
        for failure in ('unapproved', 'invalid', 'blocked_by_circuit_breaker', 'blocked_by_kill_switch'):
            with self.subTest(failure=failure):
                conn = Mock()
                with patch.object(ark, 'load_config', return_value={'db_path': 'fixture'}), \
                        patch.object(ark, 'get_connection', return_value=conn), \
                        patch.object(ark, 'initialize_schema'), \
                        patch.object(ark.apply_mod, 'plan_apply', return_value=plan) as planner, \
                        patch.object(ark.apply_mod, 'execute_apply', return_value={'status': failure, 'reason': 'fixture'}) as execute, \
                        patch('builtins.print'):
                    if failure == 'unapproved':
                        planner.side_effect = ark.apply_mod.ProposalNotApproved('fixture')
                    elif failure == 'invalid':
                        planner.return_value = {'status': 'failed', 'reason': 'fixture'}
                    with self.assertRaises(SystemExit) as error:
                        ark.cmd_apply(SimpleNamespace(proposal_id=1, preview=False))
                    self.assertEqual(error.exception.code, 1)
                    if failure in ('unapproved', 'invalid'):
                        execute.assert_not_called()
                conn.close.assert_called_once()

    def test_undo_known_failure_exits_close_connection(self):
        for missing in (True, False):
            with self.subTest(missing=missing):
                conn = Mock()
                conn.execute.return_value.fetchone.return_value = None if missing else {'action_type': 'file_move'}
                with patch.object(ark, 'load_config', return_value={'db_path': 'fixture'}), \
                        patch.object(ark, 'get_connection', return_value=conn), \
                        patch.object(ark, 'initialize_schema'), \
                        patch.object(ark.apply_mod, 'undo_apply', side_effect=ark.ExecutionDisabled('fixture')) as undo, \
                        patch('builtins.print'):
                    with self.assertRaises(SystemExit) as error:
                        ark.cmd_undo(SimpleNamespace(op_id=1))
                    self.assertEqual(error.exception.code, 1)
                    if missing:
                        undo.assert_not_called()
                conn.close.assert_called_once()
