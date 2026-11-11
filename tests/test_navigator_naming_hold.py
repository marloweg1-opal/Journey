"""Unvalidated formats cannot acquire authority; exact names survive review."""

from hashlib import sha256
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock
import unittest

from core.naming import observe_filename
from core.journal import preview_operation
from journey_navigator.guided import encoded
from journey_navigator.patrol import Patrol
from journey_navigator.workbench import Workbench
from test_navigator_context import fingerprint, make_board
from test_operational_patrol import FixtureConsent


class NamingHoldTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix='journey-naming-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.source = self.base / 'Authorized sample'
        self.source.mkdir()
        self.original = '💖🌈 PROJECT Moonstone_Reference_00_00.PNG'
        make_board(self.source / self.original)
        make_board(self.source / 'Clover Corestone.png', variation=40)
        make_board(self.source / 'Corestone Character Reference.png', variation=80)
        self.store = self.base / 'Review data'
        self.open()
        self.job = self.app.select(self.source, proposals=True)['job']
        while True:
            status = self.app.step(self.job)
            if not status['pending'] and not status['pending_folders']:
                break
        self.lock = RLock()
        self.patrol = Patrol(self.app, self.lock, approver=FixtureConsent())
        self.addCleanup(self.patrol.close)

    def open(self):
        self.app = Workbench(self.store)
        self.addCleanup(self.app.close)

    def image(self, name=None):
        return next(row for row in self.app.images(self.job, 0)['items'] if row['filename'] == (name or self.original))

    def approve(self, batch):
        binding, description = self.patrol.guided.begin_approval(batch['id'])
        self.patrol.guided.accept(batch['id'], FixtureConsent().verify(binding, description))
        return self.patrol.guided.step(batch['id'])

    def test_limited_windows_console_encoding_cannot_corrupt_or_block_unicode_preview(self):
        output = io.BytesIO()
        stream = io.TextIOWrapper(output, encoding='cp1252', errors='strict')
        with redirect_stdout(stream):
            preview = preview_operation(None, 'file_move', 3, self.original, {'dest': 'Curated/' + self.original})
        stream.flush()
        self.assertEqual(preview['target_path'], self.original)
        self.assertEqual(preview['planned_changes']['dest'], 'Curated/' + self.original)
        self.assertIn(b'\\U0001f496\\U0001f308', output.getvalue())
        stream.detach()

    def test_unicode_opaque_fields_survive_export_and_reopen_without_source_changes(self):
        before = fingerprint(self.source)
        image = self.image()
        observed = observe_filename(self.original)
        self.assertEqual(''.join(observed['parts']) + observed['extension'], self.original)
        self.assertEqual(observed['unicode_sequences'], ['💖🌈'])
        self.assertEqual([field['text'] for field in observed['numeric_fields']], ['00', '00'])
        self.assertTrue(all(field['meaning'] == 'unknown' for field in observed['numeric_fields']))
        self.assertEqual(image['observed_name'], observed)
        self.assertEqual(image['suggestion']['filename'], self.original)
        self.assertFalse(image['suggestion']['executable'])
        export = json.loads(Path(self.app.export(self.job)['path']).read_text())
        self.assertEqual(next(row for row in export['images'] if row['filename'] == self.original)['observed_name'], observed)
        self.patrol.close()
        self.app.close()
        self.open()
        self.assertEqual(self.image()['observed_name'], observed)
        self.assertEqual(fingerprint(self.source), before)

    def test_compound_reference_does_not_become_a_subject_or_an_alias(self):
        compound = self.image('Clover Corestone.png')
        self.assertEqual(compound['identity']['state'], 'unknown')
        self.assertEqual(compound['identity']['label'], '')
        evidence = next(signal for signal in compound['signals'] if signal['source'] == 'Filename')
        self.assertFalse(evidence['subjects'])
        self.assertTrue(evidence['ambiguous_references'])
        self.assertNotIn('Clover Corestone', self.app.registry['tokens']['corestone']['aliases'])
        self.assertEqual(self.image('Corestone Character Reference.png')['identity']['label'], 'Corestone')
        # An explicit registered full alias is separate evidence. The heuristic
        # must not silently erase a registry owner's deliberate definition.
        self.app.registry['tokens']['corestone']['aliases'].append('Clover Corestone')
        self.assertEqual(self.image('Clover Corestone.png')['identity']['label'], 'Corestone')

    def test_direct_rename_and_renaming_move_remain_held_after_confirmation_and_rule_edit(self):
        before = fingerprint(self.source)
        image = self.image()
        self.app.review(self.job, image['id'], 'confirm', 'Moonstone', 'Character Reference')
        self.app.rule(self.job, 'PROJECT', '{subject} - {purpose}', '')
        updated = self.image()
        self.assertEqual(updated['name']['state'], 'held_convention')
        self.assertIsNone(updated['name']['destination'])
        self.assertFalse(updated['naming_profile']['executable'])
        folder = self.source / 'Curated'
        folder.mkdir()
        for kind, target in [('rename', self.source / 'Moonstone - Character Reference.PNG'),
                             ('move', folder / 'Different name.PNG'),
                             ('rename', self.source / self.original.replace('.PNG', '.png'))]:
            with self.subTest(kind=kind, target=target):
                with self.assertRaisesRegex(ValueError, 'no validated project naming profile'):
                    self.patrol.guided.prepare(self.job, [{'kind': kind, 'asset': image['id'], 'destination': str(target)}])
        self.assertEqual(self.patrol.guided.conn.execute('SELECT count(*) FROM guided_batches').fetchone()[0], 0)
        self.assertEqual(fingerprint(self.source), before)

    def test_old_saved_rename_is_rechecked_before_an_approval_prompt(self):
        image = self.image()
        folder = self.source / 'Curated'
        folder.mkdir()
        batch = self.patrol.guided.prepare(self.job, [{'kind': 'move', 'asset': image['id'], 'destination': str(folder / self.original)}])
        # Model a persisted 0.4.0 batch. No approval callback is invoked.
        payload = json.loads(self.patrol.guided.row(batch['id'])['payload'])
        payload['operations'][0]['destination'] = str(folder / 'An old generic name.PNG')
        binding = sha256(encoded(payload).encode()).hexdigest()
        with self.patrol.guided.conn:
            self.patrol.guided.conn.execute('UPDATE guided_batches SET payload=?,binding=? WHERE id=?', (encoded(payload), binding, batch['id']))
        with self.assertRaisesRegex(ValueError, 'no validated project naming profile'):
            self.patrol.guided.begin_approval(batch['id'])
        self.assertEqual(self.patrol.guided.row(batch['id'])['status'], 'review_required')
        self.assertTrue((self.source / self.original).exists())

    @unittest.skipUnless(os.name == 'nt', 'Native Windows move and recovery')
    def test_unicode_move_close_reopen_and_exact_reversal(self):
        image = self.image()
        original = self.source / self.original
        content = original.read_bytes()
        folder = self.source / 'Curated'
        folder.mkdir()
        target = folder / self.original
        batch = self.patrol.guided.prepare(self.job, [{'kind': 'move', 'asset': image['id'], 'destination': str(target)}])
        result = self.approve(batch)
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(target.name, self.original)
        self.assertEqual(target.read_bytes(), content)
        receipt = result['progress'][0]['receipt']
        self.patrol.close()
        self.app.close()
        self.open()
        self.patrol = Patrol(self.app, self.lock, approver=FixtureConsent())
        self.addCleanup(self.patrol.close)
        inverse = self.patrol.guided.prepare_undo(self.job, receipt)
        result = self.approve(inverse)
        self.assertEqual(result['status'], 'completed', result)
        self.assertEqual(original.read_bytes(), content)
        self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()
