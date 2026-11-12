"""Eight-step housekeeping acceptance through the authenticated application API."""
import json
import os
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from time import sleep, monotonic
from urllib.request import Request, urlopen
from unittest import TestCase,main
from journey_navigator.__main__ import Navigator
from journey_navigator.workbench import Workbench
from test_operational_patrol import FixtureConsent
from tools.demo_duplicate_patrol import make_demo

class HousekeepingWorkflow(TestCase):
    def test_controlled_cleanup_history_naming_and_subsequent_patrol(self):
        with TemporaryDirectory(prefix='journey-housekeeping-e2e-') as folder:
            base=Path(folder).resolve();collection,exports,pack=make_demo(base/'Fixture')
            protected=[p for p in collection.iterdir() if '(1)' not in p.name]
            def fingerprints():return {p.name:(sha256(p.read_bytes()).hexdigest(),p.stat().st_mtime_ns) for p in protected}
            original=fingerprints();app=Workbench(base/'Checkpoint')
            try:
                with Navigator(app,approver=FixtureConsent()) as server:
                    worker=Thread(target=server.serve_forever);worker.start()
                    def api(action,**body):
                        request=Request(server.origin+'/api/inspect/'+action,data=json.dumps(body).encode(),headers={
                            'Content-Type':'application/json','Origin':server.origin,'X-Journey-Session':server.token})
                        with urlopen(request,timeout=15) as response:return json.load(response)
                    def until(action,predicate,**body):
                        deadline=monotonic()+12
                        while monotonic()<deadline:
                            value=api(action,**body)
                            if predicate(value):return value
                            sleep(.025)
                        self.fail(f'{action} failed to complete: {value}')
                    try:
                        job=api('select',path=str(collection),retain=True,proposals=True)['job']
                        for _ in range(40):
                            value=api('step',job=job)
                            if not value['pending'] and not value['pending_folders']:break
                        preview=api('pack-preview',job=job,path=str(pack));api('pack-apply',job=job,ticket=preview['ticket'],project='carebloomos')
                        before=api('images',job=job)['items']
                        api('duplicates-audit',job=job,read_references=True)
                        state=until('duplicates-status',lambda s:s['current'] and not s['running'],job=job)
                        audit=state['audit'];self.assertEqual(audit['proposed_removals'],1);self.assertTrue(audit['near_duplicates'])
                        self.assertFalse(state['permission']['enabled'])
                        preview=api('history-preview',job=job,path=str(exports));api('history-enqueue',job=job,ticket=preview['ticket'])
                        history=until('history-status',lambda s:all(x['status']=='complete' for x in s['files']),job=job)
                        after=api('images',job=job)['items']
                        primrose=next(i for i in after if i['filename'].startswith('Primrose'));self.assertEqual(primrose['identity']['label'],'Heartstone')
                        self.assertTrue(api('history-text-search',job=job,query='Primrose Hinamori')['items'])
                        api('duplicates-permission',job=job,automatic=True)
                        until('duplicates-status',lambda s:s['permission']['enabled'],job=job)
                        asset=audit['exact_groups'][0]['remove'][0]['id']
                        batch=api('duplicates-prepare',job=job,audit=audit['id'],assets=[asset])
                        api('batch-authorize',**batch)
                        until('batch-view',lambda b:b['status']=='completed',destination=batch['destination'],batch=batch['batch'])
                        self.assertFalse((collection/'Moonstone Character Sheet (1).png').exists())
                        recovery=api('duplicates-status',job=job)['recovery'][0]
                        restored=api('duplicates-restore',job=job,recovery=recovery['id']);api('batch-authorize',**restored)
                        until('batch-view',lambda b:b['status']=='completed',destination=restored['destination'],batch=restored['batch'])
                        self.assertTrue((collection/'Moonstone Character Sheet (1).png').exists())
                        # A future duplicate is discovered by the same monitor. Advance its deadline
                        # deterministically; each production tick remains one minute apart.
                        api('duplicates-watch',job=job,enabled=True,read_references=True)
                        (collection/'Moonstone Character Sheet (2).png').write_bytes((collection/'Moonstone Character Sheet.png').read_bytes())
                        for _ in range(30):
                            with server.lock:server.patrol.duplicates.due=0;server.patrol.duplicates.tick()
                            sleep(.025)
                            if not (collection/'Moonstone Character Sheet (2).png').exists():break
                        self.assertFalse((collection/'Moonstone Character Sheet (2).png').exists())
                        api('duplicates-watch',job=job,enabled=False)
                        api('duplicates-audit',job=job,read_references=True)
                        final=until('duplicates-status',lambda s:s['current'] and not s['running'],job=job)
                        self.assertTrue(final['audit']['broad_groups'])
                        saved=api('export',job=job);self.assertFalse(saved['actionable'])
                        self.assertIn('duplicate_preview',json.loads(Path(saved['path']).read_text()))
                        self.assertEqual(original,fingerprints())
                        report={'test_scope':'Disposable files, actual runtime and filesystem operations. Fixture consent, not live HEXSEED owner verification.',
                            'files_audited':audit['files_audited'],'exact_proposed':audit['proposed_removals'],
                            'variation_pairs_preserved':len(audit['near_duplicates']),'initial_cleanup_completed':True,'recovery_completed':True,
                            'subsequent_duplicate_patrol_completed':True,'exports_indexed':len(history['files']),
                            'unique_messages':history['unique_messages'],'searchable_messages':history['text_index']['indexed_messages'],
                            'source_files_unchanged_except_approved_redundant_copies':True,
                            'before_after':[{'file':old['filename'],'before_identity':old['identity']['label'],
                                'after_identity':next((i['identity']['label'] for i in after if i['id']==old['id']),None),
                                'history_citations':len(next((i['metadata']['local_history'] for i in after if i['id']==old['id']),[]))} for old in before],
                            'organization_groups':[{'label':g['label'],'assets':len(g['assets'])} for g in final['audit']['broad_groups']],
                            'save_plan_kind':saved['kind'],'physical_changes_from_import':False}
                        if target:=os.environ.get('JOURNEY_HOUSEKEEPING_REPORT'):
                            path=Path(target);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(report,indent=2)+'\n')
                    finally:server.shutdown();worker.join()
            finally:app.close()

if __name__=='__main__':main()
