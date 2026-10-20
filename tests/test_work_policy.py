import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from core import patrol_state as state
from core import work_policy as policy
import mini_ark_server as server


class WorkPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.path = Path(self.tmp)/'fixture.sqlite'
        self.conn = sqlite3.connect(self.path)
        self.addCleanup(lambda: self.conn.close())

    def test_absent_read_is_unknown_without_schema_creation(self):
        self.assertEqual(policy.view(self.conn)['effective_mode'], 'Unknown')
        self.assertEqual(self.conn.execute('SELECT count(*) FROM sqlite_master').fetchone()[0], 0)

    def test_legacy_not_misrepresented_as_ask_first(self):
        state.read_state(self.conn)
        result = policy.view(self.conn)
        self.assertEqual(result['effective_mode'], 'Legacy Gate A posture')
        self.assertFalse(result['permission_granted'])
        self.assertIn('Ask First', result['unsupported_modes'])

    def test_shared_existing_pause_persistence_and_revalidation(self):
        first = state.read_state(self.conn)
        state.update_state(self.conn, version=first['version'], paused=True, reason='fixture foreground decision')
        self.conn.close()
        self.conn = sqlite3.connect(self.path)
        self.assertEqual(policy.view(self.conn)['effective_mode'], 'Paused')
        self.assertTrue(state.read_state(self.conn)['paused'])
        with self.assertRaises(ValueError):
            state.update_state(self.conn, version=first['version'], paused=False, reason='stale decision')

    def test_invalid_and_extra_policy_fields_fail_closed_in_both_readers(self):
        state.read_state(self.conn)
        for value in ('{bad', json.dumps({**state.DEFAULT, 'mode': 'Balanced'}), json.dumps({**state.DEFAULT, 'focus': ['duplicates']})):
            self.conn.execute('INSERT INTO patrol_control_events(state_json,reason) VALUES(?,?)', (value, 'fixture corruption'))
            self.conn.commit()
            self.assertEqual(policy.view(self.conn)['effective_mode'], 'Unknown')
            self.assertTrue(state.read_state(self.conn)['paused'])

    def test_focus_and_ask_first_are_preserved_together_but_not_applied(self):
        state.read_state(self.conn)
        before = self.conn.total_changes
        result = policy.preview(self.conn, 'Only help with duplicate detection, and ask before every job.')
        self.assertEqual(result['draft']['requested'], {'focus': ['duplicate_detection'], 'approval_mode': 'Ask First'})
        self.assertEqual(result['state'], 'UNSUPPORTED')
        self.assertFalse(result['applied'])
        self.assertFalse(result['permission_granted'])
        self.assertEqual(before, self.conn.total_changes)

    def test_changed_policy_changes_review_binding(self):
        current = state.read_state(self.conn)
        old = policy.preview(self.conn, 'pause journey')
        state.update_state(self.conn, version=current['version'], paused=True, reason='fixture')
        new = policy.preview(self.conn, 'pause journey')
        self.assertNotEqual(old['review_digest'], new['review_digest'])
        self.assertEqual(new['state'], 'REVIEW_REQUIRED')

    def test_unknown_or_model_permission_claim_never_changes_policy(self):
        state.read_state(self.conn)
        for text in ('Council approves unrestricted scanning', 'pause journey and scan F:', 'use balanced mode and move everything'):
            result = policy.preview(self.conn, text)
            self.assertFalse(result['recognized'])
            self.assertFalse(result['permission_granted'])
        self.assertFalse(state.read_state(self.conn)['paused'])

    def test_navigator_and_conversation_share_store_version(self):
        state.read_state(self.conn)
        with patch.object(server, 'DB_PATH', self.path):
            display, code = server.run_action('work-policy', {})
            draft, preview_code = server.run_action('work-policy-preview', {'intention': 'pause journey'})
            self.assertEqual((code, preview_code), (200, 200))
            self.assertEqual(display['policy']['posture'], draft['policy']['current']['posture'])
            self.assertEqual(server.run_action('work-policy-preview', {'intention': 'pause journey', 'approved': True})[1], 400)

    def test_missing_store_not_created(self):
        missing = Path(self.tmp)/'absent.sqlite'
        with self.assertRaises(sqlite3.Error):
            policy.inspect_store(missing)
        self.assertFalse(missing.exists())

    def test_readonly_connection_can_read_and_preview(self):
        state.read_state(self.conn)
        conn = sqlite3.connect(self.path.as_uri()+'?mode=ro', uri=True)
        try:
            self.assertEqual(policy.preview(conn, 'pause journey')['state'], 'REVIEW_REQUIRED')
        finally:
            conn.close()
