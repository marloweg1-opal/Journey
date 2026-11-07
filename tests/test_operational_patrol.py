"""Real local work under explicit fixture consent. No executor is mocked."""

from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock
from time import monotonic, sleep, time
import os
import unittest

from journey_navigator.approval import Consent, WindowsApprover
from journey_navigator.patrol import Patrol
from journey_navigator.workbench import Workbench
from test_navigator_context import make_board, reader
from navigator_fixtures import make_link


class FixtureConsent:
    """Only this test injects a declared fixture actor. Excluded from every package."""
    def verify(self,binding,description):
        return Consent(binding,'automated-fixture-actor',time(),'Fixture approval, not owner consent')


class OperationalPatrolTests(unittest.TestCase):
    def setUp(self):
        self.temporary=TemporaryDirectory(prefix='journey-operational-')
        self.addCleanup(self.temporary.cleanup)
        self.base=Path(self.temporary.name).resolve()
        self.source=self.base/'CareBloomOS'
        self.source.mkdir()
        for index in range(30):
            make_board(self.source/f'Moonstone reference sheet v{index:02}.png',variation=index)
        self.app=Workbench(self.base/'Checkpoint',ocr=None)
        self.job=self.app.select(self.source,proposals=True)['job']
        self.lock=RLock()
        self.patrol=Patrol(self.app,self.lock,approver=FixtureConsent())
        self.addCleanup(self.app.close)
        self.addCleanup(self.patrol.close)
        self.destination=self.patrol.create(self.job,'Find and continue my artwork','Continue the project',
            'Images indexed, useful groupings and clearly exposed unresolved work')['id']

    def finish(self):
        with self.lock:
            self.patrol.begin(self.destination)
        deadline=monotonic()+30
        while monotonic()<deadline:
            with self.lock:
                value=self.patrol.status(self.destination)
            if value['state'] not in ('Inspecting','Assessing','Working','Verifying'):
                return value
            sleep(.03)
        self.fail('Patrol did not reach a bounded resting state.')

    def approve(self,batch):
        with self.lock:
            binding,description=self.patrol.guided.begin_approval(batch['id'])
            self.patrol.guided.accept(batch['id'],FixtureConsent().verify(binding,description))
            return self.patrol.guided.step(batch['id'])

    def test_foreground_organizes_and_reopens_without_repeated_work(self):
        value=self.finish()
        self.assertEqual(value['state'],'Completed')
        self.assertEqual(value['coverage']['analyzed'],30)
        self.assertGreater(value['metrics']['collections'],0)
        with self.lock:
            cursor=self.app.conn.execute('SELECT cursor FROM patrol_tasks WHERE destination=? AND kind=\'assess\'',(self.destination,)).fetchone()[0]
        self.assertEqual(self.finish()['coverage']['reused'],value['coverage']['reused'])
        with self.lock:
            self.assertEqual(self.app.conn.execute('SELECT cursor FROM patrol_tasks WHERE destination=? AND kind=\'assess\'',(self.destination,)).fetchone()[0],cursor)
        self.patrol.close(); self.app.close()
        self.app=Workbench(self.base/'Checkpoint')
        self.patrol=Patrol(self.app,self.lock,approver=FixtureConsent())
        self.addCleanup(self.app.close); self.addCleanup(self.patrol.close)
        self.assertEqual(self.patrol.status(self.destination)['objective'],value['objective'])
        self.assertEqual(self.patrol.status(self.destination)['coverage']['analyzed'],30)

    def test_real_folder_creation_uses_journal_and_rejects_occupied_target(self):
        self.finish()
        target=self.source/'Curated References'
        batch=self.patrol.guided.prepare(self.job,[{'kind':'mkdir','destination':str(target),'reason':'Keep curated reference exports together'}])
        self.assertFalse(target.exists())
        result=self.approve(batch)
        self.assertEqual(result['status'],'completed')
        self.assertTrue(target.is_dir())
        log=self.patrol.guided.history(self.job)
        self.assertEqual(log[0]['status'],'applied')
        self.assertIn('directory_identity',log[0]['new_state'])
        with self.assertRaisesRegex(ValueError,'occupied'):
            self.patrol.guided.prepare(self.job,[{'kind':'mkdir','destination':str(target)}])

    @unittest.skipUnless(os.name=='nt','Windows no-overwrite move and reversal')
    def test_real_move_native_executor_receipt_undo_and_new_occupant(self):
        self.finish()
        image=self.app.images(self.job,0)['items'][0]
        source=Path(image['path']); original=source.read_bytes()
        target=source.with_name('Moonstone - Confirmed Reference.png')
        batch=self.patrol.guided.prepare(self.job,[{'kind':'rename','asset':image['id'],'destination':str(target),'reason':'Use the established reference naming convention'}])
        result=self.approve(batch)
        self.assertEqual(result['status'],'completed',result)
        self.assertFalse(source.exists())
        self.assertEqual(target.read_bytes(),original)
        receipt=result['progress'][0]['receipt']
        inverse=self.patrol.guided.prepare_undo(self.job,receipt)
        result=self.approve(inverse)
        self.assertEqual(result['status'],'completed',result)
        self.assertEqual(source.read_bytes(),original)
        self.assertFalse(target.exists())
        self.finish()
        image=next(image for image in self.app.images(self.job,0)['items'] if image['path']==str(source))
        # Another real operation, followed by an occupied original path.
        batch=self.patrol.guided.prepare(self.job,[{'kind':'rename','asset':image['id'],'destination':str(target)}])
        moved=self.approve(batch)
        receipt=moved['progress'][0]['receipt']
        source.write_bytes(b'new occupant')
        with self.assertRaisesRegex(ValueError,'occupied'):
            self.patrol.guided.prepare_undo(self.job,receipt)
        self.assertEqual(source.read_bytes(),b'new occupant')
        self.assertEqual(target.read_bytes(),original)

    def test_outside_links_and_revoked_scopes_do_not_gain_patrol_authority(self):
        outside=self.base/'Other project'; outside.mkdir()
        make_board(outside/'Cloverstone.png')
        make_link(self.source/'External shortcut.lnk',outside)
        value=self.finish()
        self.assertEqual(value['coverage']['analyzed'],30)
        self.assertEqual(value['coverage']['link_attention'],1)
        with self.assertRaises(ValueError):
            self.patrol.guided.prepare(self.job,[{'kind':'mkdir','destination':str(outside/'No')}])
        with self.lock:
            self.app.revoke(self.job,str(self.source),'inspect')
        with self.assertRaises(PermissionError):
            self.patrol.status(self.destination)

    def test_changed_batch_and_changed_source_require_fresh_review(self):
        self.finish()
        target=self.source/'Reviewed folder'
        batch=self.patrol.guided.prepare(self.job,[{'kind':'mkdir','destination':str(target)}])
        binding,description=self.patrol.guided.begin_approval(batch['id'])
        consent=FixtureConsent().verify(binding,description)
        target.mkdir()
        with self.assertRaisesRegex(ValueError,'occupied'):
            self.patrol.guided.accept(batch['id'],consent)
        self.assertEqual(list(target.iterdir()),[])

    def test_source_mode_cannot_skip_native_account_verification(self):
        with self.assertRaises(PermissionError):
            WindowsApprover().verify('0'*64,'Fixture cannot authorize as the owner.')


if __name__=='__main__':
    unittest.main()
