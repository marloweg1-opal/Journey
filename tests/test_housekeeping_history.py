"""Historical enrichment uses the persistent runtime, not an assistant's memory."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from hashlib import sha256
from journey_navigator.workbench import Workbench
from tools.demo_duplicate_patrol import make_demo

class HousekeepingHistory(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory(prefix='journey-housekeeping-');self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name).resolve();self.collection,self.exports,self.pack=make_demo(self.base/'Demo')
        self.app=Workbench(self.base/'Checkpoint');self.addCleanup(self.app.close)
        self.job=self.app.select(self.collection,proposals=True)['job']
        for _ in range(40):
            s=self.app.step(self.job)
            if not s['pending'] and not s['pending_folders']:break
        self.app.project_registry.activate(self.job,json.loads(self.pack.read_text())['profile'])

    def image(self):return next(i for i in self.app.images(self.job,0,thumbnails=False)['items'] if i['filename']=='Primrose Hinamori Character Sheet.png')
    def ingest(self,path):
        self.app.history.enqueue(self.job,self.app.history.preview(self.job,path)['ticket'])
        for _ in range(40):
            if not self.app.history.advance():break

    def test_before_after_character_relationship_search_and_repeat(self):
        files=[*self.collection.iterdir(),*self.exports.iterdir()]
        before={p:(sha256(p.read_bytes()).hexdigest(),p.stat().st_mtime_ns) for p in files}
        image=self.image();self.assertEqual(image['identity']['state'],'unknown');identity=image['id']
        self.ingest(self.exports/'conversations-001.json');self.ingest(self.exports/'conversations-002.json')
        after=self.image();self.assertEqual(after['id'],identity);self.assertEqual(after['identity']['label'],'Heartstone')
        self.assertFalse(after['name'].get('executable'))
        result=self.app.history.text_search(self.job,'Primrose Hinamori');self.assertEqual(len(result),1)
        self.assertTrue(result[0]['authored'].startswith('2026-'));self.assertTrue(result[0]['imported'])
        status=self.app.history.status(self.job);self.assertEqual(status['unique_messages'],5);self.assertEqual(status['text_index']['indexed_messages'],5)
        self.ingest(self.exports)
        self.assertEqual(self.app.history.status(self.job)['unique_messages'],5)
        self.assertEqual(before,{p:(sha256(p.read_bytes()).hexdigest(),p.stat().st_mtime_ns) for p in files})

    def test_accepted_identity_remains_authoritative_when_history_disagrees(self):
        image=self.image();self.app.review(self.job,image['id'],'confirm','Moonstone')
        profile=json.dumps(self.app.project_registry.profile(self.job),sort_keys=True)
        self.ingest(self.exports)
        after=self.image();self.assertEqual(after['identity']['label'],'Moonstone');self.assertEqual(after['identity']['state'],'human_confirmed_identity')
        self.assertIn('Heartstone',json.dumps(after['identity']))
        self.assertEqual(profile,json.dumps(self.app.project_registry.profile(self.job),sort_keys=True))

    def test_explicit_legacy_text_backfill_reuses_existing_evidence_generation(self):
        self.ingest(self.exports)
        cursor=self.app.history.change_cursor(self.job)
        with self.app.conn:
            self.app.conn.execute('DELETE FROM history_fts');self.app.conn.execute('DELETE FROM history_text')
        self.ingest(self.exports)
        self.assertEqual(self.app.history.status(self.job)['text_index']['indexed_messages'],5)
        self.assertEqual(self.app.history.change_cursor(self.job),cursor)
        self.assertEqual(self.app.history.status(self.job)['unique_messages'],5)

if __name__=='__main__':main()
