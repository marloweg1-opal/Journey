"""Incremental evidence acceptance. Invented exports, real runtime and untouched files."""

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock
from unittest import TestCase, main
from unittest.mock import patch

from journey_navigator.patrol import Patrol
from journey_navigator.registry import PATTERN_FORMAT
from journey_navigator.workbench import Workbench
from tools.demo_integrated_pilot import illustration, native_record


class IncrementalHistory(TestCase):
    def setUp(self):
        temp = TemporaryDirectory(prefix='journey-incremental-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.assets, self.exports = self.root / 'Copies', self.root / 'Exports'
        self.assets.mkdir()
        self.exports.mkdir()
        for index, name in enumerate(('Beat Character Sheet.png', 'Melody Character Sheet.png', 'unrelated.png')):
            illustration(self.assets / name, (550 + index * 40, 350), '#55abef')
        self.app = Workbench(self.root / 'Checkpoint')
        self.addCleanup(self.app.close)
        self.job = self.app.select(self.assets, proposals=True)['job']
        for _ in range(40):
            progress = self.app.step(self.job)
            if not progress['pending'] and not progress['pending_folders']:
                break
        self.app.project_registry.activate(self.job, {'format': PATTERN_FORMAT, 'project': 'CareBloomOS',
            'signals': ['CareBloomOS', 'Musicstone'], 'rules': []})
        self.lock = RLock()
        self.patrol = Patrol(self.app, self.lock)
        # Drive the actual checkpoint engine deterministically rather than race its worker.
        self.patrol.stop.set()
        self.patrol.wake.set()
        self.patrol.worker.join(5)
        self.addCleanup(self.patrol.close)
        self.destination = self.patrol.create(self.job, 'Organize project', 'Reuse evidence', 'Trace conclusions')['id']
        self.run_patrol()

    def run_patrol(self):
        self.patrol.begin(self.destination)
        for _ in range(40):
            self.patrol.cycle(self.destination)
            if self.patrol.row(self.destination)['state'] not in ('Inspecting', 'Assessing', 'Working', 'Verifying'):
                return
        self.fail('Patrol failed to complete its bounded work.')

    def snapshot(self):
        return {str(path): (sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
                for folder in (self.assets, self.exports) for path in folder.glob('*') if path.is_file()}

    def import_file(self, path):
        plan = self.app.history.preview(self.job, path)
        self.app.history.enqueue(self.job, plan['ticket'])
        for _ in range(50):
            if not self.app.history.advance():
                return
        self.fail('History did not complete.')

    def saved(self):
        return {row['asset']: row['record'] for row in self.app.conn.execute('SELECT asset,record FROM patrol_assets WHERE destination=?', (self.destination,))}

    def image_ids(self):
        return {row['filename']: row['id'] for row in self.app.images(self.job, 0, thumbnails=False)['items']}

    def test_overlapping_exports_reassess_only_affected_assets_and_preserve_corrections(self):
        old = ('original', 'user', 'CareBloomOS: `Beat Character Sheet.png` is a character reference.', [])
        first = self.exports / 'conversations-001.json'
        first.write_text(json.dumps([native_record('original-chat', [old], 'CareBloomOS')]), encoding='utf-8')
        self.import_file(first)
        ids = self.image_ids()
        self.app.review(self.job, ids['unrelated.png'], 'purpose', purpose='Emblem')
        self.run_patrol()
        before_records = self.saved()
        reviews = [tuple(row) for row in self.app.conn.execute('SELECT * FROM reviews')]
        observations = [tuple(row) for row in self.app.conn.execute('SELECT * FROM observations')]
        epoch = self.app.job(self.job)['epoch']
        second = self.exports / 'conversations-002.json'
        second.write_text(json.dumps([native_record('overlapping-chat', [old,
            ('new-duo', 'user', 'Musicstone: Beat and Melody each have a reference sheet.', [])], 'CareBloomOS')]), encoding='utf-8')
        untouched = self.snapshot()
        self.assertNotEqual(json.loads(before_records[ids['Beat Character Sheet.png']])['identity']['label'], 'Musicstone')
        with patch.object(self.app, '_analyze', side_effect=AssertionError('Knowledge changes must reuse observations')):
            self.import_file(second)
            self.run_patrol()
        after = self.saved()
        status = self.patrol.status(self.destination)
        self.assertEqual(status['incremental']['reassessed'], 2)
        self.assertEqual(status['incremental']['reused'], 1)
        self.assertEqual(before_records[ids['unrelated.png']], after[ids['unrelated.png']])
        beat = json.loads(after[ids['Beat Character Sheet.png']])
        self.assertEqual(beat['identity']['label'], 'Musicstone')
        self.assertEqual(json.loads(after[ids['Melody Character Sheet.png']])['identity']['label'], 'Musicstone')
        link = next(claim for claim in beat['metadata']['local_history'] if claim['kind'] == 'entity')
        self.assertEqual(link['source']['message'], 'new-duo')
        self.assertEqual(link['source']['archive'], second.name)
        self.assertEqual(self.image_ids(), ids)
        self.assertEqual(self.app.job(self.job)['epoch'], epoch)
        self.assertEqual([tuple(row) for row in self.app.conn.execute('SELECT * FROM reviews')], reviews)
        self.assertEqual([tuple(row) for row in self.app.conn.execute('SELECT * FROM observations')], observations)
        self.assertEqual(self.snapshot(), untouched)
        delta = self.app.history.status(self.job)['incremental'][0]
        self.assertEqual(delta['overlapping_claims'], 1)
        self.assertEqual(delta['new_claims'], 2)
        self.assertEqual(delta['affected_assets'], 2)
        self.assertEqual(self.app.history.status(self.job)['unique_messages'], 2)
        self.assertEqual(self.patrol.guided.history(self.job), [])
        self.assertEqual(self.patrol.guided.conn.execute('SELECT count(*) FROM guided_batches').fetchone()[0], 0)

    def test_overlap_only_reuses_every_assessment_and_changed_claim_is_traceable(self):
        old = ('stable-message', 'user', 'CareBloomOS: `unrelated.png` is a CareRail interface.', [])
        first = self.exports / 'conversations-001.json'
        first.write_text(json.dumps([native_record('chat', [old], 'CareBloomOS')]), encoding='utf-8')
        self.import_file(first)
        self.run_patrol()
        saved = self.saved()
        duplicate = self.exports / 'conversations-002.json'
        duplicate.write_bytes(first.read_bytes())
        untouched = self.snapshot()
        self.import_file(duplicate)
        self.run_patrol()
        self.assertEqual(self.saved(), saved)
        self.assertEqual(self.patrol.status(self.destination)['incremental']['reassessed'], 0)
        self.assertEqual(self.patrol.status(self.destination)['incremental']['reused'], 3)
        self.assertEqual(self.app.history.status(self.job)['incremental'][0]['new_claims'], 0)
        self.assertEqual(self.snapshot(), untouched)
        # A later assertion is retained alongside its predecessor, never promoted to approval.
        changed = self.exports / 'conversations-003.json'
        changed.write_text(json.dumps([native_record('chat', [('stable-message', 'user',
            'CareBloomOS: `unrelated.png` is a wallpaper.', [])], 'CareBloomOS')]), encoding='utf-8')
        self.import_file(changed)
        self.run_patrol()
        delta = self.app.history.status(self.job)['incremental'][0]
        self.assertEqual(delta['changed_claims'], 1)
        self.assertEqual(self.patrol.status(self.destination)['incremental']['reassessed'], 1)
        claims = self.app.history.evidence(self.job, self.app.project_registry.profile(self.job), 'unrelated.png')
        self.assertEqual({c['family'] for c in claims}, {'CareRail UI / Design', 'Wallpaper'})
        self.assertEqual(self.app.images(self.job, 0, asset_ids=[self.image_ids()['unrelated.png']], thumbnails=False)['items'][0]['purpose']['state'], 'conflicting_evidence')

    def test_new_history_keeps_a_directly_accepted_identity_and_records_its_challenge(self):
        ids = self.image_ids()
        self.app.review(self.job, ids['Beat Character Sheet.png'], 'confirm', 'Heartstone')
        self.run_patrol()
        before = [tuple(row) for row in self.app.conn.execute('SELECT * FROM reviews')]
        new = self.exports / 'conversations-new.json'
        new.write_text(json.dumps([native_record('new', [('duo', 'user',
            'Musicstone: Beat and Melody each have a reference sheet.', [])], 'CareBloomOS')]), encoding='utf-8')
        self.import_file(new)
        self.run_patrol()
        beat = json.loads(self.saved()[ids['Beat Character Sheet.png']])
        self.assertEqual(beat['identity']['state'], 'human_confirmed_identity')
        self.assertEqual(beat['identity']['label'], 'Heartstone')
        self.assertIn('Musicstone', beat['identity']['conflicts'])
        self.assertEqual([tuple(row) for row in self.app.conn.execute('SELECT * FROM reviews')], before)
        self.assertTrue(any(c['kind'] == 'entity' for c in beat['metadata']['local_history']))

    def test_forgetting_history_clears_derived_work_and_forces_a_safe_fresh_assessment(self):
        export = self.exports / 'conversations-new.json'
        export.write_text(json.dumps([native_record('new', [('duo', 'user',
            'Musicstone: Beat and Melody each have a reference sheet.', [])], 'CareBloomOS')]), encoding='utf-8')
        self.import_file(export)
        self.run_patrol()
        with self.app.conn:
            self.app.history.forget(self.job)
        self.run_patrol()
        self.assertEqual(len(self.saved()), 3)
        self.assertTrue(all(not json.loads(row)['metadata']['local_history'] for row in self.saved().values()))

    def test_incremental_queue_survives_a_patrol_restart_and_profile_changes_force_full_review(self):
        for index in range(28):
            illustration(self.assets / f'Beat Character Sheet {index}.png', (550 + index, 380), '#55abef')
        self.app.refresh(self.job)
        for _ in range(50):
            progress = self.app.step(self.job)
            if not progress['pending'] and not progress['pending_folders']:
                break
        self.run_patrol()
        export = self.exports / 'conversations-new.json'
        export.write_text(json.dumps([native_record('new', [('duo', 'user',
            'Musicstone: Beat and Melody each have a reference sheet.', [])], 'CareBloomOS')]), encoding='utf-8')
        self.import_file(export)
        self.patrol.begin(self.destination)
        for _ in range(4):
            self.patrol.cycle(self.destination)
            if self.app.conn.execute('SELECT count(*) FROM patrol_evidence_queue WHERE destination=?', (self.destination,)).fetchone()[0] == 6:
                break
        self.assertEqual(self.patrol.status(self.destination)['incremental']['reassessed'], 24)
        self.patrol.close()
        self.patrol = Patrol(self.app, self.lock)
        self.patrol.stop.set()
        self.patrol.wake.set()
        self.patrol.worker.join(5)
        self.addCleanup(self.patrol.close)
        self.run_patrol()
        status = self.patrol.status(self.destination)
        self.assertEqual(status['incremental']['reassessed'], 30)
        self.assertEqual(status['incremental']['reused'], 1)
        self.assertEqual(self.app.conn.execute('SELECT count(*) FROM patrol_evidence_queue').fetchone()[0], 0)
        self.app.project_registry.activate(self.job, {'format': PATTERN_FORMAT, 'project': 'CareBloomOS',
            'signals': ['CareBloomOS', 'Musicstone', 'Heartstone'], 'rules': []})
        self.run_patrol()
        self.assertEqual(self.patrol.status(self.destination)['incremental']['reused'], 0)
        self.assertEqual(self.patrol.status(self.destination)['incremental']['reassessed'], 31)

    def test_authorized_background_reconciliation_updates_virtual_work_without_execution(self):
        first = self.exports / 'conversations-001.json'
        first.write_text('[]', encoding='utf-8')
        self.import_file(self.exports)
        self.run_patrol()
        self.app.history.monitor_enable(self.job)
        new = self.exports / 'conversations-002.json'
        new.write_text(json.dumps([native_record('new', [('duo', 'user',
            'Musicstone: Beat and Melody each have a reference sheet.', [])], 'CareBloomOS')]), encoding='utf-8')
        untouched = self.snapshot()
        self.app.history.monitor_tick()
        while self.app.history.advance():
            pass
        with patch.object(self.patrol.guided, 'step', side_effect=AssertionError('Background evidence must not execute')):
            with patch.object(self.app, '_analyze', side_effect=AssertionError('Reuse observations')):
                self.patrol._background_history()
        status = self.patrol.status(self.destination)
        self.assertEqual(status['incremental']['reassessed'], 2)
        self.assertEqual(status['incremental']['reused'], 1)
        self.assertEqual(self.snapshot(), untouched)
        self.assertEqual(json.loads(self.saved()[self.image_ids()['Beat Character Sheet.png']])['identity']['label'], 'Musicstone')
        self.assertNotEqual(status['state'], 'Working')
        self.assertEqual(self.patrol.guided.history(self.job), [])
        self.app.history.pause(self.job)
        self.patrol.history_due = 0
        with patch.object(self.patrol, '_assess', side_effect=AssertionError('Pause disables background work')):
            self.patrol._background_history()

    def test_monitored_import_is_explicit_bounded_session_only_and_respects_pause(self):
        first = self.exports / 'conversations-001.json'
        first.write_text('[]', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'reviewed export folder'):
            self.app.history.monitor_enable(self.job)
        self.import_file(self.exports)
        self.assertFalse(self.app.history.monitor_status(self.job)['enabled'])
        self.app.history.monitor_enable(self.job)
        new = self.exports / 'conversations-002.json'
        new.write_text(json.dumps([native_record('new', [('new', 'user', 'Musicstone: Beat and Melody each have a reference sheet.', [])], 'CareBloomOS')]), encoding='utf-8')
        nested = self.exports / 'Nested'
        nested.mkdir()
        (nested / 'conversations-secret.json').write_bytes(new.read_bytes())
        (self.exports / 'private.json').write_bytes(new.read_bytes())
        untouched = self.snapshot()
        self.app.history.monitor_tick()
        self.assertLessEqual(self.app.history.monitor_status(self.job)['checked'], 24)
        self.assertEqual(self.app.history.monitor_status(self.job)['queued'], 1)
        while self.app.history.advance():
            pass
        self.assertEqual(len(self.app.history.status(self.job)['files']), 2)
        self.assertEqual(self.snapshot(), untouched)
        self.app.history.pause(self.job)
        self.assertFalse(self.app.history.monitor_status(self.job)['enabled'])
        from journey_navigator.history import ArchiveHistory
        reopened = ArchiveHistory(self.app)
        self.assertFalse(reopened.monitor_status(self.job)['enabled'])
        self.assertIsNone(reopened.monitor_status(self.job)['available_folder'])


if __name__ == '__main__':
    main()
