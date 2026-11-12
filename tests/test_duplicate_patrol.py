"""Disposable collections; actual SHA256, filesystem removal and recovery, fixture consent only."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock
from time import time
from unittest import TestCase, main
from PIL import Image
from journey_navigator.approval import Consent
from journey_navigator.workbench import Workbench
from journey_navigator.patrol import Patrol

class DuplicateTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(prefix='journey-duplicates-');self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name).resolve();self.root=self.base/'Copies';self.root.mkdir()
        image=Image.new('RGB',(320,240));image.putdata([(x%256,y%256,(x+y)%256) for y in range(240) for x in range(320)])
        image.save(self.root/'Heartstone.png')
        (self.root/'Heartstone (1).png').write_bytes((self.root/'Heartstone.png').read_bytes())
        image.resize((160,120)).save(self.root/'small.jpg',quality=80)
        (self.root/'required.txt').write_text('a required distinct asset')
        (self.root/'required (1).txt').write_text('a required distinct asset')
        (self.root/'project.ini').write_text('image=required (1).txt')
        for n in range(5):(self.root/f'unique{n}.txt').write_text(f'unique {n}')
        self.app=Workbench(self.base/'Checkpoint');self.addCleanup(self.app.close)
        self.job=self.app.select(self.root,proposals=True)['job']
        self.p=Patrol(self.app,RLock());self.p.stop.set();self.p.wake.set();self.p.worker.join(5);self.addCleanup(self.p.close)
        self.dest=self.p.create(self.job,'Cleanup','Reduce repetition','Retain source and recover removal')['id'];self.p.begin(self.dest)
        self.d=self.p.duplicates

    def audit(self):
        self.d.begin(self.job,True)
        for _ in range(50):
            if self.d.audit_step(self.job):return self.d.status(self.job)['audit']
        self.fail('Audit did not finish')

    def grant(self,automatic=False):
        binding,_=self.d.grant_preview(self.job,automatic)
        self.d.activate(binding,Consent(binding,'fixture-only',time(),'Disposable test actor, not owner consent'))

    def approve(self,batch):
        binding,_=self.p.guided.begin_approval(batch['id'])
        self.p.guided.accept(batch['id'],Consent(binding,'fixture-only',time(),'Disposable test actor, not owner consent'))
        return self.p.guided.step(batch['id'])

    def selected(self,audit):return next(i['id'] for g in audit['exact_groups'] for i in g['remove'] if i['name']=='Heartstone (1).png')

    def test_preview_locked_then_real_removal_and_restore(self):
        a=self.audit();self.assertEqual(a['files_audited'],11)
        self.assertTrue(a['near_duplicates']);self.assertTrue(a['broad_groups'])
        self.assertTrue(any(g['keep']['name']=='required (1).txt' for g in a['exact_groups']))
        asset=self.selected(a)
        with self.assertRaises(PermissionError):self.d.prepare(self.job,a['id'],[asset])
        original=(self.root/'Heartstone (1).png').read_bytes();self.grant()
        batch=self.d.prepare(self.job,a['id'],[asset]);result=self.approve(batch)
        self.assertEqual(result['status'],'completed',result)
        self.assertFalse((self.root/'Heartstone (1).png').exists())
        for path in ('Heartstone.png','small.jpg','required.txt','required (1).txt'):self.assertTrue((self.root/path).exists())
        recovery=self.d.recovery_status(self.job)[0];self.assertEqual(recovery['state'],'removed')
        restored=self.approve(self.d.prepare_restore(self.job,recovery['id']))
        self.assertEqual(restored['status'],'completed',restored)
        self.assertEqual((self.root/'Heartstone (1).png').read_bytes(),original)

    def test_changed_keeper_blocks_execution(self):
        a=self.audit();self.grant();batch=self.d.prepare(self.job,a['id'],[self.selected(a)])
        (self.root/'Heartstone.png').write_bytes(b'changed')
        with self.assertRaises(ValueError):self.approve(batch)
        self.assertTrue((self.root/'Heartstone (1).png').exists())

    def test_hash_reuse_and_session_monitor_finds_subsequent_copy(self):
        self.audit();self.app.refresh(self.job);a=self.audit()
        self.assertEqual(a['hashes_reused'],11)
        self.grant(True);self.d.watch(self.job,True,True)
        (self.root/'Heartstone (2).png').write_bytes((self.root/'Heartstone.png').read_bytes())
        for _ in range(30):
            self.d.due=0;self.d.tick()
            batch=self.p.guided.conn.execute("SELECT id FROM guided_batches WHERE status='approved'").fetchone()
            if batch:break
        self.assertIsNotNone(batch,self.d.status(self.job))
        while self.p.guided.row(batch[0])['status'] in ('approved','working'):self.p.guided.step(batch[0])
        self.assertFalse((self.root/'Heartstone (2).png').exists())
        self.assertTrue((self.root/'required (1).txt').exists())
        self.d.revoke(self.job);self.assertFalse(self.d.permission(self.job)['enabled'])

    def test_expiry_removes_checkpoint_not_retained_source(self):
        a=self.audit();self.grant();self.approve(self.d.prepare(self.job,a['id'],[self.selected(a)]))
        with self.app.conn:self.app.conn.execute('UPDATE duplicate_recovery SET expires=0')
        self.d.expire();self.assertEqual(self.d.recovery_status(self.job)[0]['state'],'expired')
        self.assertFalse(list(self.d.recovery.glob('*.gz')))
        self.assertTrue((self.root/'Heartstone.png').exists())


    def test_accepted_path_outranks_copy_hint(self):
        self.audit()
        asset=self.app.conn.execute("SELECT id FROM files WHERE job=? AND path=?",(self.job,str(self.root/'Heartstone (1).png'))).fetchone()[0]
        self.app.review(self.job,asset,'confirm','Heartstone')
        a=self.audit();group=next(g for g in a['exact_groups'] if g['keep']['name']=='Heartstone (1).png')
        self.assertEqual(group['keep']['id'],asset)
        self.assertFalse(any(i['automatic_candidate'] for i in group['remove']))

    def test_late_reference_and_revocation_hold_without_removal(self):
        a=self.audit();self.grant();batch=self.d.prepare(self.job,a['id'],[self.selected(a)])
        (self.root/'new.ini').write_text('image=Heartstone (1).png')
        with self.assertRaises(PermissionError):self.approve(batch)
        (self.root/'new.ini').unlink()
        batch=self.d.prepare(self.job,a['id'],[self.selected(a)])
        binding,_=self.p.guided.begin_approval(batch['id'])
        self.p.guided.accept(batch['id'],Consent(binding,'fixture-only',time(),'fixture-only'))
        self.d.revoke(self.job)
        result=self.p.guided.step(batch['id'])
        self.assertEqual(result['status'],'blocked')
        self.assertTrue((self.root/'Heartstone (1).png').exists())

    def test_occupied_restore_never_overwrites(self):
        a=self.audit();self.grant();self.approve(self.d.prepare(self.job,a['id'],[self.selected(a)]))
        r=self.d.recovery_status(self.job)[0]
        (self.root/'Heartstone (1).png').write_text('new occupant')
        with self.assertRaisesRegex(ValueError,'occupied'):self.d.prepare_restore(self.job,r['id'])
        self.assertEqual((self.root/'Heartstone (1).png').read_text(),'new occupant')


    def test_restart_retains_recovery_but_discards_execution_permission(self):
        a=self.audit();self.grant(True);self.approve(self.d.prepare(self.job,a['id'],[self.selected(a)]))
        recovery=self.d.recovery_status(self.job)[0]
        self.p.close()
        self.p=Patrol(self.app,RLock());self.p.stop.set();self.p.wake.set();self.p.worker.join(5);self.addCleanup(self.p.close)
        self.d=self.p.duplicates
        self.assertFalse(self.d.permission(self.job)['enabled']);self.assertFalse(self.d.watches)
        self.assertEqual(self.d.recovery_status(self.job)[0]['id'],recovery['id'])
        with self.assertRaises(PermissionError):self.d.prepare_restore(self.job,recovery['id'])
        self.grant();self.assertEqual(self.approve(self.d.prepare_restore(self.job,recovery['id']))['status'],'completed')


    def test_interrupted_staging_holds_its_entire_exact_group(self):
        (self.root/'.journey-remove-interrupted').write_bytes((self.root/'Heartstone.png').read_bytes())
        a=self.audit()
        group=next(g for g in a['exact_groups'] if g['keep']['name'].startswith('.journey-'))
        self.assertEqual(group['remove'],[])
        self.assertEqual(len(group['held']),2)
        self.assertTrue(all('interrupted' in i['hold'] for i in group['held']))

    def test_paused_foreground_and_monitor_fail_with_a_clear_result(self):
        self.p.pause(self.dest)
        with self.assertRaisesRegex(PermissionError,'paused'):self.d.queue(self.job)
        with self.assertRaisesRegex(PermissionError,'paused'):self.d.watch(self.job,True)
        self.assertFalse(self.d.pending_audits);self.assertFalse(self.d.watches)

if __name__=='__main__':main()
