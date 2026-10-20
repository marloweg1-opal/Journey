import sqlite3
import unittest
from unittest.mock import Mock, patch
from core.recovery_domain import RecoveryAuthority, recover_derivative, storage_preflight


class ProviderReadGuardTests(unittest.TestCase):
    def test_malformed_effort_ceiling_denies_before_probes(self):
        for ceiling in (None, True, False, 3, -1, 99, 3.5, '3', float('nan'), float('inf')):
            with self.subTest(ceiling=ceiling):
                provider, conn = Mock(), Mock()
                authority = RecoveryAuthority(scope='C:\\fixture', max_effort=ceiling,
                    derivative_output_authorized=True, authority_receipt='fixture',
                    output_scope='C:\\output')
                with patch('core.recovery_domain.require_path_not_held') as guard, \
                        patch('core.media_inventory.safe_metadata') as metadata, \
                        patch('core.recovery_domain.storage_preflight') as capacity:
                    with self.assertRaises(ValueError):
                        recover_derivative(conn, 'C:\\fixture\\source',
                                           'C:\\output', provider, authority)
                guard.assert_not_called()
                metadata.assert_not_called()
                capacity.assert_not_called()
                self.assertEqual(provider.mock_calls, [])
                self.assertEqual(conn.mock_calls, [])

    def test_malformed_derivative_approval_denies_before_probes(self):
        cases = [(value, 'fixture') for value in (False, None, 0, 1, 'true', 'false', [], {})]
        cases += [(True, value) for value in ('', '   ', None, 1, True, [], {})]
        for approval, receipt in cases:
            with self.subTest(approval=approval, receipt=receipt):
                provider = Mock()
                conn = Mock()
                authority = RecoveryAuthority(scope='C:\\fixture',
                    derivative_output_authorized=approval, authority_receipt=receipt,
                    output_scope='C:\\output')
                with patch('core.recovery_domain.require_path_not_held') as guard, \
                        patch('core.media_inventory.safe_metadata') as metadata, \
                        patch('core.recovery_domain.storage_preflight') as capacity:
                    result = recover_derivative(conn, 'C:\\fixture\\source',
                                                'C:\\output', provider, authority)
                self.assertEqual(result['state'], 'AWAITING_DERIVATIVE_AUTHORITY')
                self.assertFalse(result['retirement_authorized'])
                guard.assert_not_called()
                metadata.assert_not_called()
                capacity.assert_not_called()
                self.assertEqual(provider.mock_calls, [])
                self.assertEqual(conn.mock_calls, [])

    def test_capacity_denial_precedes_disk_probe(self):
        with patch('core.recovery_domain.require_path_not_held',
                   side_effect=PermissionError('POLICY_UNAVAILABLE')), patch(
                   'core.recovery_domain.shutil.disk_usage') as disk:
            result = storage_preflight('F:\\fixture', 100)
        disk.assert_not_called()
        self.assertIn('POLICY_UNAVAILABLE', result['observation_error'])
        self.assertNotEqual(result['state'], 'RESOURCE_FEASIBLE')

    def test_source_hold_precedes_workspace_probe_and_provider(self):
        conn = sqlite3.connect(':memory:')
        self.addCleanup(conn.close)
        provider = Mock()
        authority = RecoveryAuthority(scope='F:\\', derivative_output_authorized=True,
                                      authority_receipt='fixture', output_scope='C:\\fixture')
        with patch('core.recovery_domain.require_path_not_held',
                   side_effect=PermissionError('SOURCE_HELD')), patch(
                   'core.media_inventory.safe_metadata') as metadata:
            result = recover_derivative(conn, 'F:\\source', 'C:\\fixture', provider, authority)
        metadata.assert_not_called()
        provider.attempt.assert_not_called()
        self.assertEqual(result['state'], 'REVIEW')
        self.assertIn('SOURCE_HELD', result['reason'])
