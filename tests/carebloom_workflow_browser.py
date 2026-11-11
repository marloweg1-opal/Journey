"""One guided CareBloomOS path through the real Navigator using disposable fixtures."""

from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile

from playwright.sync_api import expect, sync_playwright
from navigator_browser import running_navigator
from tools.demo_carebloom_collection import make_demo


def snapshot(paths):
    return {str(path): (sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns) for path in paths}


def exercise(browser, runtime, base):
    collection, exports, pack = make_demo(base / 'Demonstration')
    protected = [*collection.iterdir(), *exports.iterdir(), pack]
    before = snapshot(protected)
    data = base / 'Review checkpoint'
    with running_navigator(runtime, data, base) as url:
        page = browser.new_page(viewport={'width': 1100, 'height': 900})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(url)
        page.get_by_label('Keep a local checkpoint', exact=False).check()
        page.get_by_label('Suggest names and draft a plan', exact=True).check()
        page.get_by_label('Folder or shortcut path').fill(str(collection))
        page.get_by_role('button', name='Inspect selection', exact=True).click()
        expect(page.locator('[data-count="analyzed"]')).to_have_text('10', timeout=60000)
        expect(page.locator('#collection-flow-next')).to_have_text('Add project context', timeout=30000)
        page.locator('#collection-flow-next').click()
        page.get_by_label('Local project pack or evidence ZIP path').fill(str(pack))
        page.get_by_role('button', name='Preview project pack', exact=True).click()
        page.get_by_role('button', name='Activate CareBloomOS for this scope', exact=True).click()
        expect(page.locator('#collection-flow-next')).to_have_text('Add historical context')
        page.locator('#collection-flow-next').click()
        expect(page.locator('#history-status')).to_contain_text('No local conversation archive')
        page.get_by_label('Local conversation export or folder path').fill(str(exports))
        page.get_by_role('button', name='Preview archive selection', exact=True).click()
        page.get_by_role('button', name='Import these reviewed exports', exact=True).click()
        expect(page.locator('#history-status')).to_contain_text('2 exports indexed · 3 distinct messages', timeout=30000)
        expect(page.locator('#collection-flow-next')).to_have_text('Review interpretations')
        page.locator('#collection-flow-next').click()
        for filename, content in [('Beat Character Sheet.png', 'Musicstone'),
                                  ('Melody Character Sheet.png', 'Musicstone'),
                                  ('render_17.png', 'CareRail UI / Design'),
                                  ('Heart Touchstone.png', 'Touchstone'),
                                  ('Cloudstone Armory Sheet.png', 'Equipment / Design Reference')]:
            card = page.locator('[data-image]').filter(has=page.get_by_role('heading', name=filename, exact=True))
            expect(card).to_contain_text(content)
        compound = page.locator('[data-image]').filter(has=page.get_by_role('heading', name='Heart Corestone Crystal.png', exact=True))
        expect(compound).to_contain_text('Identity open')
        panel = page.locator('[data-image]').filter(has=page.get_by_role('heading', name='render_17.png', exact=True))
        panel.get_by_text('Evidence and naming preview', exact=True).click()
        expect(panel).to_contain_text('fixture-panel')
        expect(panel).to_contain_text('no validated rule')
        page.locator('#collection-flow-next').click()
        page.get_by_label('Why this matters', exact=True).fill('Find and review CareBloomOS assets with their supporting history.')
        page.get_by_role('button', name='Save Destination', exact=True).click()
        page.get_by_role('button', name='Begin or resume Patrol', exact=True).click()
        expect(page.locator('#patrol-state')).not_to_have_text('Not started')
        expect(page.locator('#patrol-work')).to_contain_text('Outcome review remains open.', timeout=30000)
        expect(page.locator('#patrol-collections')).to_contain_text('CareRail UI / Design')
        page.get_by_role('button', name='Save organization preview', exact=True).click()
        expect(page.locator('#patrol-preview-result')).to_contain_text('Organization preview saved to', timeout=30000)
        saved = json.loads(next(data.glob('Inspection-*.json')).read_text(encoding='utf-8'))
        assert len(saved['images']) == 10
        assert all(not image['name'].get('executable') for image in saved['images'])
        indexed = {image['filename']: image for image in saved['images']}
        assert indexed['Beat Character Sheet.png']['identity']['label'] == 'Musicstone'
        assert indexed['Heart Corestone Crystal.png']['identity']['state'] == 'unknown'
        assert indexed['render_17.png']['metadata']['local_history'][0]['source']['message'] == 'fixture-panel'
        assert not errors, errors
        assert snapshot(protected) == before
        page.locator('.journey-tools').get_by_role('button', name='Manage', exact=True).click()
        page.get_by_role('button', name='Close Navigator', exact=True).click()
        expect(page.get_by_text('Navigator is closed.', exact=True)).to_be_visible()
        page.close()
    with running_navigator(runtime, data, base) as url:
        page = browser.new_page()
        page.goto(url)
        page.locator('.quick [data-select="manage"]').click()
        page.get_by_role('button', name='Open saved inspection', exact=True).click()
        expect(page.locator('[data-count="analyzed"]')).to_have_text('10')
        expect(page.locator('#collection-flow-next')).to_have_text('Review interpretations', timeout=30000)
        page.close()
    assert snapshot(protected) == before
    print('CareBloomOS guided workflow passed: select, inspect, explicit pack/history grants, contextual review, virtual organization, saved preview and checkpoint reopening; source hashes and mtimes preserved.')


if __name__ == '__main__':
    import argparse, sys
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, default=Path(sys.executable))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='journey-carebloom-workflow-') as folder, sync_playwright() as driver:
        browser = driver.chromium.launch(headless=True, executable_path=os.environ.get('JOURNEY_TEST_BROWSER'))
        try:
            exercise(browser, args.runtime.resolve(), Path(folder).resolve())
        finally:
            browser.close()
