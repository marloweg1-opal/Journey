import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.recovery_domain import Effort, RecoveryAuthority, recover_derivative


class RecoveryResourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'original.bin'
        self.source.write_bytes(b'original')
        self.output = self.root / 'derivatives'
        self.output.mkdir()
        self.conn = sqlite3.connect(':memory:')
        self.addCleanup(self.conn.close)
        self.authority = RecoveryAuthority(str(self.root), Effort.SAFE_RECONSTRUCTION,
                                           True, 'fixture', str(self.output))
        self.provider = Mock(name='fixture-provider')
        self.provider.name = 'fixture'
        self.provider.levels = [Effort.SAFE_RECONSTRUCTION]
        self.provider.attempt.return_value = b'derivative'
        self.provider.prove_usable.return_value = {'usable': True, 'checks': {'fixture': True}}

    def run_recovery(self, **kwargs):
        return recover_derivative(self.conn, self.source, self.output, self.provider,
                                  self.authority, max_bytes=100, storage_margin_bytes=10, **kwargs)

    def test_insufficient_space_stops_before_source_identity_or_provider(self):
        with patch('core.recovery_domain.shutil.disk_usage', return_value=SimpleNamespace(free=109)):
            with patch('core.recovery_inspection.file_identity') as identity:
                result = self.run_recovery()
        self.assertEqual(result['state'], 'RESOURCE_BLOCKED')
        identity.assert_not_called()
        self.provider.attempt.assert_not_called()
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertEqual(self.source.read_bytes(), b'original')

    def test_unknown_capacity_stops_before_provider(self):
        with patch('core.recovery_domain.shutil.disk_usage', side_effect=OSError('fixture unavailable')):
            result = self.run_recovery()
        self.assertEqual(result['state'], 'RESOURCE_UNKNOWN')
        self.provider.attempt.assert_not_called()
        self.assertEqual(list(self.output.iterdir()), [])

    def test_space_lost_after_provider_is_journaled_without_output(self):
        with patch('core.recovery_domain.shutil.disk_usage',
                   side_effect=[SimpleNamespace(free=110), SimpleNamespace(free=0)]):
            result = self.run_recovery()
        self.assertEqual(result['state'], 'RESOURCE_BLOCKED')
        self.assertEqual(self.conn.execute('SELECT state FROM recovery_attempts').fetchone()[0],
                         'RESOURCE_BLOCKED')
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertEqual(self.source.read_bytes(), b'original')

    def test_sufficient_space_preserves_existing_verification_path(self):
        with patch('core.recovery_domain.shutil.disk_usage', return_value=SimpleNamespace(free=110)):
            result = self.run_recovery()
        self.assertEqual(result['state'], 'VERIFIED')
        self.assertEqual(Path(result['output']).read_bytes(), b'derivative')
        self.assertEqual(self.source.read_bytes(), b'original')

    def test_capacity_becomes_unknown_before_write(self):
        with patch('core.recovery_domain.shutil.disk_usage',
                   side_effect=[SimpleNamespace(free=110), OSError('capacity unavailable')]):
            result = self.run_recovery()
        self.assertEqual(result['state'], 'RESOURCE_UNKNOWN')
        self.assertEqual(self.conn.execute('SELECT state FROM recovery_attempts').fetchone()[0],
                         'RESOURCE_UNKNOWN')
        self.assertEqual(list(self.output.iterdir()), [])
        self.assertEqual(self.source.read_bytes(), b'original')

    def test_missing_authority_still_blocks_even_with_space(self):
        with patch('core.recovery_domain.shutil.disk_usage') as capacity:
            result = recover_derivative(self.conn, self.source, self.output, self.provider,
                                        RecoveryAuthority(str(self.root)))
        self.assertEqual(result['state'], 'AWAITING_DERIVATIVE_AUTHORITY')
        capacity.assert_not_called()
        self.provider.attempt.assert_not_called()

    def assert_drift_stops_provider(self, replacement):
        from core.recovery_inspection import file_identity
        original_identity = file_identity(self.source)
        def drift(_, **kwargs):
            self.source.write_bytes(replacement)
            return original_identity
        with patch('core.recovery_inspection.file_identity', side_effect=drift):
            result = self.run_recovery()
        self.assertEqual(result['state'], 'REVIEW')
        self.provider.attempt.assert_not_called()
        self.assertEqual(list(self.output.iterdir()), [])

    def test_growth_after_identity_stops_before_provider(self):
        self.assert_drift_stops_provider(b'x' * 1000)

    def test_truncation_after_identity_stops_before_provider(self):
        self.assert_drift_stops_provider(b'x')

    def test_equal_size_replacement_stops_before_provider(self):
        self.assert_drift_stops_provider(b'changed!')

    def test_task_budget_blocks_initial_content_open(self):
        self.source.write_bytes(b'x' * 101)
        with patch.object(Path, 'open') as opener:
            result = self.run_recovery()
        self.assertEqual(result['state'], 'REVIEW')
        opener.assert_not_called()
        self.provider.attempt.assert_not_called()

    def test_identity_invalid_budgets_stop_before_metadata(self):
        from core.recovery_inspection import file_identity
        for budget in (0, -1, True, '100', None, 1.5):
            with self.subTest(budget=budget), patch('core.media_inventory.safe_metadata') as metadata:
                self.assertIsNone(file_identity(self.source, max_bytes=budget))
                metadata.assert_not_called()

    def test_identity_accepts_exact_budget(self):
        from core.recovery_inspection import file_identity
        identity = file_identity(self.source, max_bytes=8)
        self.assertIsNotNone(identity)
        self.assertEqual(identity['size'], 8)
