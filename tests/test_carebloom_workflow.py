"""The collection-to-review contract over authenticated Navigator HTTP."""

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from time import sleep
from urllib.request import Request, urlopen
from unittest import TestCase, main
from unittest.mock import patch

from journey_navigator.__main__ import Navigator
from journey_navigator.workbench import Workbench
from tools.demo_carebloom_collection import make_demo


class CareBloomCollectionWorkflow(TestCase):
    def test_collection_history_context_virtual_preview_and_no_source_operations(self):
        with TemporaryDirectory(prefix='carebloom-http-workflow-') as temporary:
            base = Path(temporary).resolve()
            collection, exports, pack = make_demo(base / 'Fixture')
            sources = [*collection.iterdir(), *exports.iterdir(), pack]
            def snapshot():
                return {str(p): (sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns) for p in sources}
            before = snapshot()
            app = Workbench(base / 'Checkpoint')
            try:
                with Navigator(app) as navigator:
                    thread = Thread(target=navigator.serve_forever)
                    thread.start()
                    def api(action, **body):
                        request = Request(navigator.origin + '/api/inspect/' + action, data=json.dumps(body).encode(), headers={
                            'Content-Type': 'application/json', 'Origin': navigator.origin, 'X-Journey-Session': navigator.token})
                        with urlopen(request, timeout=10) as result:
                            return json.load(result)
                    try:
                        selected = api('select', path=str(collection), retain=True, proposals=True)
                        job = selected['job']
                        for _ in range(30):
                            summary = api('step', job=job)
                            if not summary['pending'] and not summary['pending_folders']:
                                break
                        self.assertEqual(summary['analyzed'], 10)
                        initial = {image['filename']: image for image in api('images', job=job)['items']}
                        self.assertEqual(initial['render_17.png']['purpose']['state'], 'unknown')
                        draft = api('pack-preview', job=job, path=str(pack))
                        api('pack-apply', job=job, ticket=draft['ticket'], project='carebloomos')
                        self.assertEqual(api('history-status', job=job)['unique_messages'], 0)
                        selection = api('history-preview', job=job, path=str(exports))
                        self.assertEqual(api('history-status', job=job)['files'], [])
                        api('history-enqueue', job=job, ticket=selection['ticket'])
                        for _ in range(100):
                            history = api('history-status', job=job)
                            if all(s['status'] == 'complete' for s in history['files']):
                                break
                            sleep(.02)
                        self.assertEqual(history['unique_messages'], 3)
                        self.assertFalse(history['monitor']['enabled'])
                        images = {image['filename']: image for image in api('images', job=job)['items']}
                        self.assertEqual({k:v['id'] for k,v in images.items()}, {k:v['id'] for k,v in initial.items()})
                        self.assertEqual(images['render_17.png']['purpose']['label'], 'CareRail UI / Design')
                        self.assertEqual(images['Beat Character Sheet.png']['identity']['label'], 'Musicstone')
                        self.assertEqual(images['Beat Character Sheet.png']['identity']['state'], 'proposed_identity')
                        self.assertEqual(images['Melody Character Sheet.png']['identity']['label'], 'Musicstone')
                        self.assertEqual(images['Opalstone Chibi.png']['identity']['label'], 'Corestone')
                        self.assertEqual(images['Heart Corestone Crystal.png']['identity']['state'], 'unknown')
                        self.assertEqual(images['Heart Touchstone.png']['purpose']['label'], 'Touchstone')
                        self.assertEqual(images['Cloudstone Armory Sheet.png']['purpose']['label'], 'Equipment / Design Reference')
                        self.assertTrue(all(not image['name'].get('executable') for image in images.values()))
                        api('review', job=job, asset=images['Beat Character Sheet.png']['id'], decision='confirm', label='Musicstone', purpose='Character Reference')
                        destination = api('destination-create', job=job, objective='Organize this CareBloomOS collection',
                                          why='Find supported assets with their sources', success='Review virtual groups and open questions')['id']
                        with patch.object(navigator.interpreter, 'interpret', side_effect=AssertionError('No model is needed')):
                            self.assertEqual(api('goal-plan', destination=destination, instruction='Organize the selected folder.')['state'], 'AWAITING_REVIEW')
                        api('patrol-begin', destination=destination)
                        for _ in range(100):
                            work = api('patrol-status', destination=destination)
                            if work['state'] not in ('Inspecting', 'Assessing', 'Working', 'Verifying'):
                                break
                            sleep(.02)
                        self.assertIn('CareRail UI / Design', {item['name'] for item in work['collections']})
                        self.assertGreater(work['metrics']['unresolved'], 0)
                        self.assertEqual(work['batches'], [])
                        self.assertEqual(work['metrics']['physical_verified'], 0)
                        output = api('export', job=job)
                        saved = json.loads(Path(output['path']).read_text(encoding='utf-8'))
                        self.assertEqual(len(saved['images']), 10)
                        render = next(i for i in saved['images'] if i['filename'] == 'render_17.png')
                        self.assertEqual(render['metadata']['local_history'][0]['source']['message'], 'fixture-panel')
                        self.assertEqual(snapshot(), before)
                    finally:
                        navigator.shutdown()
                        thread.join(10)
            finally:
                app.close()


if __name__ == '__main__':
    main()
