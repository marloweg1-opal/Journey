import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from core import bounded_assessment as a
from core.placement import load_placement_doctrine
import mini_ark_server as server


class AssessmentTests(unittest.TestCase):
    def setUp(self):
        # Fixture-only policy substitution; production always uses the hold store.
        self.enterContext(patch.object(a, 'require_path_not_held'))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'source'
        self.root.mkdir()
        self.db = self.base / 'fixture.sqlite'
        self.conn = sqlite3.connect(self.db)
        self.addCleanup(lambda: self.conn.close())
        self.doctrine = load_placement_doctrine(Path(__file__).resolve().parents[1])
        fixture = dict(self.doctrine['locations'][0])
        fixture.update(id='fixture_staging', path=str(self.root), aliases=[], legacy_aliases=[],
                       canonicality='transient_canonical', purpose='Pending classification')
        self.doctrine['locations'].append(fixture)

    def authorize(self, path):
        path = Path(path)
        return path == self.root or self.root in path.parents or path in self.root.parents

    def start(self):
        return a.start(self.conn, self.root, self.doctrine, self.authorize)

    def test_complete_retained_report_no_content_reads_or_source_writes(self):
        target = self.root / 'example.lua'
        target.write_bytes(b'fixture content')
        before = target.stat()
        run = self.start()
        with patch('builtins.open', side_effect=AssertionError('No content reads')):
            result = a.batch(self.conn, run, self.authorize)
        self.assertEqual(result['state'], 'COMPLETE')
        self.assertEqual(result['files'], 1)
        self.assertEqual(target.read_bytes(), b'fixture content')
        self.assertEqual(target.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(result['placement'][0]['classification'], 'RULE_MATCH_NOT_CONTENT_VERDICT')
        self.assertEqual(result['supported_discrepancies'], [])
        self.assertEqual(result['content_reads'], 0)
        self.assertEqual(result['managed_file_mutations'], 0)

    def test_duplicate_start_and_completed_batch_do_not_repeat(self):
        run = self.start()
        a.batch(self.conn, run, self.authorize)
        self.assertEqual(self.start(), run)
        with patch.object(a.os, 'scandir', side_effect=AssertionError('repeat')):
            self.assertEqual(a.batch(self.conn, run, self.authorize)['batch']['entries_visited'], 0)

    def test_resume_pending_directories_after_connection_restart(self):
        for name in ('a', 'b'):
            (self.root/name).mkdir()
            (self.root/name/'file.txt').write_text('fixture')
        run = self.start()
        result = a.batch(self.conn, run, self.authorize, max_directories=1)
        self.assertEqual(result['state'], 'PENDING')
        self.conn.close()
        self.conn = sqlite3.connect(self.db)
        result = a.batch(self.conn, run, self.authorize)
        self.assertEqual(result['state'], 'COMPLETE')
        self.assertEqual(result['files'], 2)

    def test_interruption_preserves_observation_and_has_one_bounded_retry(self):
        (self.root/'one.txt').write_text('fixture')
        run = self.start()
        def interrupted():
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            a.batch(self.conn, run, self.authorize, checkpoint=interrupted)
        self.assertEqual(a.report(self.conn, run)['files'], 1)
        result = a.batch(self.conn, run, self.authorize)
        self.assertEqual(result['state'], 'COMPLETE')
        self.assertEqual(result['files'], 1)

    def test_repeated_interruption_is_held_without_third_enumeration(self):
        (self.root/'one.txt').write_text('fixture')
        run = self.start()
        def interrupted():
            raise KeyboardInterrupt()
        for _ in range(2):
            with self.assertRaises(KeyboardInterrupt):
                a.batch(self.conn, run, self.authorize, checkpoint=interrupted)
        with patch.object(a.os, 'scandir', side_effect=AssertionError('third attempt')):
            result = a.batch(self.conn, run, self.authorize)
        self.assertEqual(result['state'], 'COMPLETE_WITH_GAPS')
        self.assertEqual(result['files'], 1)

    def test_real_child_exit_preserves_checkpoint(self):
        (self.root/'one.txt').write_text('fixture')
        run = self.start()
        script = "import sqlite3,os; from core import bounded_assessment as a; a.require_path_not_held=lambda p: None; c=sqlite3.connect(%r); a.batch(c,%d,lambda p: True,checkpoint=lambda: os._exit(19))" % (str(self.db), run)
        result = subprocess.run([sys.executable, '-B', '-c', script], cwd=Path(__file__).resolve().parents[1], timeout=15, capture_output=True)
        self.assertEqual(result.returncode, 19, result.stderr)
        self.assertEqual(a.report(self.conn, run)['files'], 1)
        self.assertEqual(a.batch(self.conn, run, self.authorize)['state'], 'COMPLETE')

    def test_entry_budget_retains_partial_and_does_not_loop(self):
        for name in ('a', 'b', 'c'):
            (self.root/name).write_text(name)
        run = self.start()
        result = a.batch(self.conn, run, self.authorize, max_entries=1)
        self.assertEqual(result['files'], 1)
        self.assertEqual(result['state'], 'COMPLETE_WITH_GAPS')
        self.assertEqual(result['batch']['entries_visited'], 1)
        self.assertEqual(a.batch(self.conn, run, self.authorize)['batch']['entries_visited'], 0)

    def test_revoked_authority_fails_before_source_probe(self):
        run = self.start()
        with patch.object(a, 'safe_metadata', side_effect=AssertionError('probe')):
            with self.assertRaises(PermissionError):
                a.batch(self.conn, run, lambda p: False)

    def test_f_drive_denied_before_policy_or_probe(self):
        with patch.object(a, 'safe_metadata', side_effect=AssertionError('probe')):
            with self.assertRaises(PermissionError):
                a.start(self.conn, 'F:\\held', self.doctrine, lambda p: self.fail('F policy called'))

    def test_missing_authorization_does_not_create_tables(self):
        with self.assertRaises(PermissionError):
            a.start(self.conn, self.root, self.doctrine, None)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM sqlite_master').fetchone()[0], 0)

    def test_hold_or_unavailable_policy_stops_before_metadata(self):
        run = self.start()
        with patch.object(a, 'require_path_not_held', side_effect=PermissionError('SOURCE_HELD')), patch.object(a, 'safe_metadata') as probe:
            with self.assertRaises(PermissionError):
                a.batch(self.conn, run, self.authorize)
        probe.assert_not_called()

    def test_alias_paths_rejected_without_probing_f(self):
        for path in ('\\\\?\\F:\\held', '\\\\localhost\\F$\\held', 'F:relative'):
            with self.subTest(path=path), patch.object(a, 'safe_metadata') as probe:
                with self.assertRaises((ValueError, PermissionError)):
                    a.start(self.conn, path, self.doctrine, lambda p: True)
                probe.assert_not_called()

    def test_changed_directory_after_interruption_not_retried(self):
        (self.root/'one').write_text('fixture')
        run = self.start()
        with self.assertRaises(KeyboardInterrupt):
            a.batch(self.conn, run, self.authorize, checkpoint=lambda: (_ for _ in ()).throw(KeyboardInterrupt()))
        self.conn.execute("UPDATE assessment_directories SET signature='changed'")
        self.conn.commit()
        with patch.object(a.os, 'scandir', side_effect=AssertionError('changed directory traversal')):
            result = a.batch(self.conn, run, self.authorize)
        self.assertEqual(result['state'], 'COMPLETE_WITH_GAPS')

    def test_reparse_or_unreadable_directory_is_a_gap_not_congruence(self):
        run = self.start()
        with patch.object(a, 'safe_metadata', side_effect=ValueError('Reparse path')):
            result = a.batch(self.conn, run, self.authorize)
        self.assertFalse(result['coverage_complete'])
        self.assertEqual(result['files'], 0)

    def test_invalid_budgets_fail_before_source_access(self):
        run = self.start()
        for key, value in [('max_entries', True), ('max_entries', 1001), ('max_seconds', float('nan')), ('max_seconds', 6), ('max_directories', 0)]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                a.batch(self.conn, run, self.authorize, **{key:value})

    def test_time_budget_keeps_committed_partial_evidence(self):
        (self.root/'one').write_text('fixture')
        run = self.start()
        clock = [0.0]
        def checkpoint():
            clock[0] = 3.0
        with patch.object(a.time, 'monotonic', side_effect=lambda: clock[0]):
            result = a.batch(self.conn, run, self.authorize, checkpoint=checkpoint)
        self.assertEqual(result['files'], 1)
        self.assertEqual(result['state'], 'COMPLETE_WITH_GAPS')
        self.assertIn('budget', result['held'][0]['reason'].lower())

    def test_bridge_rejects_concurrent_batch_and_cross_process_lock(self):
        self.fixture_server()
        from core.process_lock import process_lock
        with patch.object(server, 'ASSESSMENT_POLICY', {'scope': str(self.root), 'authorize': self.authorize}):
            server.ASSESSMENT_LOCK.acquire()
            try:
                self.assertEqual(server.run_action('assessment-continue', {})[1], 409)
            finally:
                server.ASSESSMENT_LOCK.release()
            with process_lock(str(self.db)+'.assessment.lock'):
                self.assertEqual(server.run_action('assessment-continue', {})[1], 409)

    def test_production_schema_baseline_compatibility(self):
        from db.database import initialize_schema
        self.conn.row_factory = sqlite3.Row
        initialize_schema(self.conn)
        result = a.historical_baseline(self.conn, doctrine=self.doctrine)
        self.assertEqual(result['retained_files'], 0)
        self.assertIsNone(result['scan'])

    def test_doctrine_change_requires_new_review(self):
        self.start()
        self.doctrine['placement_policy'] += 1
        with self.assertRaises(ValueError):
            self.start()

    def fixture_server(self):
        config = self.base/'config'
        config.mkdir(exist_ok=True)
        (config/'canonical_placement.json').write_text(json.dumps(self.doctrine))
        self.conn.executescript('''CREATE TABLE scans(id,root_path,started_at,completed_at,status,files_scanned,last_committed_path);
        CREATE TABLE files(canonical_path,size_bytes,last_seen_at);''')
        self.enterContext(patch.object(server, 'ROOT', self.base))
        self.enterContext(patch.object(server, 'DB_PATH', self.db))

    def test_navigator_end_to_end_and_retained_receipt(self):
        self.fixture_server()
        (self.root/'example.txt').write_text('unchanged')
        with patch.object(server, 'ASSESSMENT_POLICY', {'scope': str(self.root), 'authorize': self.authorize}):
            result, code = server.run_action('assessment-continue', {})
            self.assertEqual(code, 200, result)
            self.assertEqual(result['assessment']['state'], 'COMPLETE')
            receipt = result['assessment']['id']
            result, code = server.run_action('assessment-status', {})
            self.assertEqual(code, 200)
            self.assertEqual(result['assessment']['id'], receipt)
            self.assertEqual(result['assessment']['files'], 1)
            self.assertFalse(result['can_continue'])

    def test_server_denies_payload_scope_and_absent_policy(self):
        self.fixture_server()
        with patch.object(server, 'ASSESSMENT_POLICY', None):
            self.assertEqual(server.run_action('assessment-continue', {})[1], 403)
            self.assertEqual(server.run_action('assessment-continue', {'scope': 'F:\\'})[1], 400)
            result, code = server.run_action('assessment-status', {})
            self.assertEqual(code, 200)
            self.assertFalse(result['can_continue'])
        self.assertIsNone(self.conn.execute("SELECT name FROM sqlite_master WHERE name='assessment_runs'").fetchone())

    def test_baseline_does_not_treat_saved_running_as_live(self):
        self.fixture_server()
        self.conn.execute("INSERT INTO scans VALUES(9,?,'2026-10-16 07:01:51',NULL,'running',32974,'checkpoint')", (r'R:\In_Transit',))
        self.conn.execute("INSERT INTO files VALUES(?,20,'2026-10-16 07:06:31')", (r'r:\in_transit\en_route\fixture',))
        self.conn.commit()
        with patch.object(a.os, 'scandir', side_effect=AssertionError('baseline traversed source')):
            result = a.historical_baseline(self.conn)
        self.assertEqual(result['retained_files'], 1)
        self.assertEqual(result['scan']['saved_status'], 'running')
        self.assertIn('not process liveness', result['limitations'][1])


if __name__ == '__main__':
    unittest.main()
