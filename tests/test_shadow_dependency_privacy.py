import sqlite3
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from core.dependency_evidence import inspect_references
from core.perception_policy import set_policy


class ShadowDependencyPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'fixture.ini'
        self.path.write_text('icon=asset.png')
        self.conn = sqlite3.connect(':memory:')
        self.addCleanup(self.conn.close)

    def inspect(self):
        with patch('core.dependency_evidence.live_discover', return_value=(
            [{'canonical_path': str(self.path)}], {'complete': True}
        )), patch('core.dependency_evidence.require_path_not_held'):
            return inspect_references(['asset.png'], [self.tmp.name], privacy_conn=self.conn)

    def test_default_sealed_does_not_open_content(self):
        with patch('pathlib.Path.open') as opened:
            result = self.inspect()
        opened.assert_not_called()
        self.assertEqual(result['bytes_read'], 0)
        self.assertEqual(result['dependency_state'], 'UNKNOWN')
        self.assertIn('PRIVACY_DENIED', result['errors'][0]['reason'])

    def test_missing_or_closed_registry_never_opens_content(self):
        closed = sqlite3.connect(':memory:')
        closed.close()
        for kwargs in ({}, {'privacy_conn': None}, {'privacy_conn': closed}):
            with self.subTest(kwargs=kwargs), patch(
                'core.dependency_evidence.live_discover', return_value=(
                    [{'canonical_path': str(self.path)}], {'complete': True})
            ), patch('pathlib.Path.open') as opened:
                result = inspect_references(['asset.png'], [self.tmp.name], **kwargs)
            opened.assert_not_called()
            self.assertEqual(result['bytes_read'], 0)
            self.assertEqual(result['checked'], [])
            self.assertEqual(result['references'], [])
            self.assertEqual(result['errors'][0]['reason'], 'PRIVACY_POLICY_UNAVAILABLE')
            self.assertFalse(result['scope_coverage'][0]['content_inspection_complete'])
            self.assertEqual(result['dependency_state'], 'UNKNOWN')

    def test_wrong_purpose_or_missing_retention_denies(self):
        for purposes, retention in [(('other',), True), (('dependency_inspection',), False)]:
            set_policy(self.conn, self.tmp.name, 'LIMITED', reason='fixture',
                       purposes=purposes, retention=retention)
            with patch('pathlib.Path.open') as opened:
                result = self.inspect()
            opened.assert_not_called()
            self.assertFalse(result['scope_coverage'][0]['content_inspection_complete'])

    def test_limited_explicit_inspection_retention_allows_fixture(self):
        set_policy(self.conn, self.tmp.name, 'LIMITED', reason='fixture',
                   purposes=('dependency_inspection',), retention=True)
        result = self.inspect()
        self.assertTrue(result['references'])
        self.assertFalse(result['dependency_clearance'])

    def test_script_text_matching_does_not_claim_parser_coverage(self):
        set_policy(self.conn, self.tmp.name, 'LIMITED', reason='fixture',
                   purposes=('dependency_inspection',), retention=True)
        for suffix in ('.ps1', '.lua', '.js', '.yaml', '.md'):
            with self.subTest(suffix=suffix):
                self.path = Path(self.tmp.name) / ('fixture' + suffix)
                self.path.write_text('asset.png')
                result = self.inspect()
                self.assertTrue(result['references'])
                checked = result['checked'][0]
                self.assertEqual(checked['reference_method'], 'TEXT_MATCHING_ONLY')
                self.assertFalse(checked['structured_parser_supported'])
                self.assertFalse(checked['dependency_semantics_complete'])
                self.assertFalse(result['dependency_clearance'])

    def test_structured_parser_still_does_not_prove_complete_semantics(self):
        set_policy(self.conn, self.tmp.name, 'LIMITED', reason='fixture',
                   purposes=('dependency_inspection',), retention=True)
        self.path = Path(self.tmp.name) / 'fixture.json'
        self.path.write_text('{"image": "asset.png"}')
        result = self.inspect()
        checked = result['checked'][0]
        self.assertTrue(checked['structured_parser_supported'])
        self.assertEqual(checked['reference_method'], 'STRUCTURED_LITERALS_AND_TEXT_MATCHING')
        self.assertFalse(checked['dependency_semantics_complete'])
        self.assertFalse(result['dependency_clearance'])

    def test_no_raw_values_or_configuration_keys_retained(self):
        set_policy(self.conn, self.tmp.name, 'LIMITED', reason='fixture',
                   purposes=('dependency_inspection',), retention=True)
        self.path.write_text('[PRIVATE_SECTION_SENTINEL]\nSECRET_KEY_SENTINEL=asset.png\nother=PRIVATE_VALUE_SENTINEL')
        result = self.inspect()
        serialized = json.dumps(result)
        for marker in ('PRIVATE_SECTION_SENTINEL', 'SECRET_KEY_SENTINEL', 'PRIVATE_VALUE_SENTINEL'):
            self.assertNotIn(marker, serialized)
        self.assertEqual(result['structured_candidates'], [])
        self.assertTrue(result['references'])

    def test_parse_and_codec_errors_cannot_quote_content(self):
        set_policy(self.conn, self.tmp.name, 'LIMITED', reason='fixture',
                   purposes=('dependency_inspection',), retention=True)
        self.path.write_text('PRIVATE_PARSE_SENTINEL without section')
        result = self.inspect()
        self.assertNotIn('PRIVATE_PARSE_SENTINEL', json.dumps(result))
        self.assertEqual(result['errors'][0]['reason'], 'parse_error')
        self.path.write_bytes(b'PRIVATE_CODEC_SENTINEL\xff')
        result = self.inspect()
        self.assertNotIn('PRIVATE_CODEC_SENTINEL', json.dumps(result))
        self.assertEqual(result['errors'][0]['reason'], 'inspection_failed')

    def test_revocation_during_parse_discards_evidence(self):
        set_policy(self.conn, self.tmp.name, 'LIMITED', reason='fixture',
                   purposes=('dependency_inspection',), retention=True)

        def revoke(path, content):
            set_policy(self.conn, self.tmp.name, 'SEALED', reason='fixture revocation')
            return ([{'field': 'PRIVATE_KEY', 'resolved': 'asset.png'}],
                    ['PRIVATE_PARSE_ERROR'])

        with patch('core.dependency_evidence.structured_references', side_effect=revoke):
            result = self.inspect()
        self.assertGreater(result['bytes_read'], 0)
        self.assertEqual(result['checked'], [])
        self.assertEqual(result['references'], [])
        self.assertEqual(result['structured_candidates'], [])
        self.assertEqual(result['errors'][0]['reason'], 'PRIVACY_DENIED')
        self.assertNotIn('PRIVATE_', json.dumps(result))
        self.assertFalse(result['scope_coverage'][0]['content_inspection_complete'])
        self.assertEqual(result['dependency_state'], 'UNKNOWN')
