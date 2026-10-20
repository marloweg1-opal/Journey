import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import ark


class ApplyCliOutcomeTests(unittest.TestCase):
    def run_case(self, applied, failed):
        conn = Mock()
        plan = {'status': 'planned', 'total_items': 2, 'blocked_count': 0,
                'blocked': [], 'downgraded_count': 0, 'to_apply': [{}, {}]}
        result = {'status': 'completed', 'applied_count': applied,
                  'failed_count': failed,
                  'failed': [{'path': 'fixture', 'reason': 'fixture rejection'}] if failed else []}
        with patch.object(ark, 'load_config', return_value={'db_path': 'fixture'}), \
                patch.object(ark, 'get_connection', return_value=conn), \
                patch.object(ark, 'initialize_schema'), \
                patch.object(ark.apply_mod, 'plan_apply', return_value=plan), \
                patch.object(ark.apply_mod, 'execute_apply', return_value=result), \
                patch('builtins.print') as output:
            args = SimpleNamespace(proposal_id=1, preview=False)
            if failed:
                with self.assertRaises(SystemExit) as error:
                    ark.cmd_apply(args)
                self.assertEqual(error.exception.code, 1)
                label = '[PARTIAL FAILURE]' if applied else '[FAILED] Applied:'
                self.assertTrue(any(label in str(call) for call in output.call_args_list))
            else:
                ark.cmd_apply(args)
                self.assertTrue(any('[SUCCESS] Applied:' in str(call) for call in output.call_args_list))
        conn.close.assert_called_once()

    def test_partial_failure_exits_nonzero(self):
        self.run_case(1, 1)

    def test_all_failed_exits_nonzero(self):
        self.run_case(0, 2)

    def test_success_remains_success(self):
        self.run_case(2, 0)
