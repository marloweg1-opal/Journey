"""Confirmation must be literal JSON true at both HTTP and helper boundaries."""
import unittest
from unittest.mock import patch

import mini_ark_server as bridge


class BridgeConfirmationTypeTests(unittest.TestCase):
    def test_apply_rejects_non_boolean_approval_before_reading_or_running(self):
        for value in (None, False, 0, 1, 'false', 'true', [], [True], {'yes': True}):
            with self.subTest(value=value), \
                    patch.object(bridge, '_proposal_fingerprint') as inspect, \
                    patch.object(bridge, '_run_command') as run:
                result, status = bridge.apply_proposal(1, True, value)
                self.assertEqual(status, 409)
                self.assertFalse(result['ok'])
                inspect.assert_not_called()
                run.assert_not_called()

    def test_undo_rejects_non_boolean_approval_before_connecting(self):
        for value in (None, False, 0, 1, 'false', 'true', [], [True], {'yes': True}):
            with self.subTest(value=value), patch.object(bridge, '_connect') as connect:
                result, status = bridge.undo_operation_bridge(1, value)
                self.assertEqual(status, 409)
                self.assertFalse(result['ok'])
                connect.assert_not_called()

    def test_http_routes_preserve_confirmation_type(self):
        handler = object.__new__(bridge.Handler)
        for route, function in (('/api/proposals/1/apply', 'apply_proposal'),
                                ('/api/undo/1', 'undo_operation_bridge')):
            for value in ('false', 1, True, None):
                with self.subTest(route=route, value=value), \
                        patch.object(bridge, '_read_json_body', return_value={'confirmed': value}), \
                        patch.object(bridge, function, return_value=({'ok': False}, 409)) as action, \
                        patch.object(bridge, '_json_response'):
                    handler.path = route
                    handler._post()
                    self.assertIs(action.call_args.kwargs['confirmed'], value)

    def test_true_still_requires_a_valid_preview(self):
        with patch.object(bridge, '_proposal_fingerprint', return_value='fixture'), \
                patch.object(bridge, 'PREVIEW_RECEIPTS', {}), \
                patch.object(bridge, '_run_command') as run:
            result, status = bridge.apply_proposal(1, True, True)
            self.assertEqual(status, 409)
            self.assertFalse(result['ok'])
            run.assert_not_called()

    def test_preview_recheck_failure_never_issues_receipt(self):
        for failure in (OSError('fixture unavailable'), ValueError('fixture missing')):
            with self.subTest(failure=type(failure).__name__), \
                    patch.object(bridge, '_proposal_fingerprint', side_effect=['fixture', failure]), \
                    patch.object(bridge, 'PREVIEW_RECEIPTS', {}) as receipts, \
                    patch.object(bridge, '_run_command', return_value={'ok': True}) as run, \
                    patch.object(bridge.secrets, 'token_urlsafe') as issue:
                result, status = bridge.apply_proposal(1, False, False)
                self.assertEqual(status, 409)
                self.assertFalse(result['ok'])
                self.assertIn('could not be verified', result['error'])
                self.assertEqual(receipts, {})
                issue.assert_not_called()
                self.assertIn('--preview', run.call_args.args[0])

    def test_failed_execution_consumes_preview_receipt(self):
        with patch.object(bridge, '_proposal_fingerprint', return_value='fixture'), \
                patch.object(bridge, 'PREVIEW_RECEIPTS', {'token': (1, 'fixture', 200)}), \
                patch.object(bridge.time, 'monotonic', return_value=100), \
                patch.object(bridge, '_run_command', return_value={'ok': False}) as run:
            result, _ = bridge.apply_proposal(1, True, True, 'token')
            self.assertFalse(result['ok'])
            retry, status = bridge.apply_proposal(1, True, True, 'token')
            self.assertEqual(status, 409)
            self.assertFalse(retry['ok'])
            run.assert_called_once()

    def test_expired_receipt_cannot_execute(self):
        with patch.object(bridge, '_proposal_fingerprint', return_value='fixture'), \
                patch.object(bridge, 'PREVIEW_RECEIPTS', {'token': (1, 'fixture', 100)}), \
                patch.object(bridge.time, 'monotonic', return_value=101), \
                patch.object(bridge, '_run_command') as run:
            result, status = bridge.apply_proposal(1, True, True, 'token')
            self.assertEqual(status, 409)
            self.assertFalse(result['ok'])
            run.assert_not_called()

    def test_receipt_cannot_authorize_another_proposal(self):
        with patch.object(bridge, '_proposal_fingerprint', return_value='fixture'), \
                patch.object(bridge, 'PREVIEW_RECEIPTS', {'token': (1, 'fixture', 200)}), \
                patch.object(bridge.time, 'monotonic', return_value=100), \
                patch.object(bridge, '_run_command') as run:
            result, status = bridge.apply_proposal(2, True, True, 'token')
            self.assertEqual(status, 409)
            self.assertFalse(result['ok'])
            run.assert_not_called()
