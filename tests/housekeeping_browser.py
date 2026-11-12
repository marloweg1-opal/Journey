"""Visible housekeeping and Save Plan feedback; fixture account approval only."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from playwright.sync_api import expect,sync_playwright
from patrol_browser import navigator
from tools.demo_duplicate_patrol import make_demo


def run(browser,base):
    collection,_,_=make_demo(base/'Disposable demonstration')
    with navigator(base/'Checkpoint',None) as server:
        page=browser.new_page(viewport={'width':1100,'height':900});errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)));page.goto(server.url)
        page.get_by_label('Keep a local checkpoint',exact=False).check()
        page.get_by_label('Suggest names and draft a plan',exact=True).check()
        page.get_by_label('Folder or shortcut path').fill(str(collection))
        page.get_by_role('button',name='Inspect selection',exact=True).click()
        expect(page.locator('[data-count="analyzed"]')).to_have_text('13',timeout=60000)
        page.get_by_text('Duplicate Patrol and broad organization',exact=True).click()
        page.locator('#duplicate-read-references').check()
        page.get_by_role('button',name='Audit duplicates',exact=True).click()
        expect(page.locator('#duplicate-report')).to_contain_text('1 exact copies proposed',timeout=30000)
        expect(page.locator('#duplicate-status')).to_contain_text('removal locked')
        group=page.locator('#duplicate-report > details').filter(has_text='Keep Moonstone Character Sheet.png')
        group.locator('summary').click();group.locator('[data-duplicate-asset]').check()
        page.get_by_text('Establish cleanup permission',exact=True).click()
        page.get_by_role('button',name='Review scoped cleanup permission',exact=True).click()
        page.get_by_role('button',name='Refresh report',exact=True).click()
        expect(page.locator('#duplicate-status')).to_contain_text('removal enabled',timeout=30000)
        page.get_by_role('button',name='Review selected exact removals as one batch',exact=True).click()
        expect(page.locator('#patrol-batch-details')).to_contain_text('dedupe_delete',timeout=30000)
        page.get_by_role('button',name='Authorize exact batch with my Windows account',exact=True).click()
        expect(page.locator('#patrol-batch-details')).to_contain_text('completed',timeout=30000)
        assert not (collection/'Moonstone Character Sheet (1).png').exists()
        page.locator('.journey-tools').get_by_role('button',name='Inspect',exact=True).click()
        page.get_by_role('button',name='Refresh report',exact=True).click()
        page.get_by_role('button',name='Review restore',exact=True).click()
        expect(page.locator('#patrol-batch-details')).to_contain_text('dedupe_restore')
        page.get_by_role('button',name='Authorize exact batch with my Windows account',exact=True).click()
        expect(page.locator('#patrol-batch-details')).to_contain_text('completed',timeout=30000)
        assert (collection/'Moonstone Character Sheet (1).png').exists()
        page.locator('.journey-tools').get_by_role('button',name='Inspect',exact=True).click()
        page.route('**/api/inspect/export',lambda route:route.fulfill(status=503,content_type='application/json',body='{"error":"Fixture disk write failure"}'))
        page.get_by_role('button',name='Save plan',exact=True).click()
        expect(page.locator('#inspect-export-result')).to_contain_text('Save failed: Fixture disk write failure')
        page.unroute('**/api/inspect/export')
        page.get_by_role('button',name='Save plan',exact=True).click()
        expect(page.locator('#inspect-export-result')).to_contain_text('Saved inspection snapshot:')
        assert not errors,errors
        page.close()
    print('Housekeeping browser passed: preview, locked removal, deliberate scope grant, batch review, removal, restore and visible Save Plan success/failure. Fixture actor only.')

if __name__=='__main__':
    with TemporaryDirectory(prefix='journey-housekeeping-browser-') as folder,sync_playwright() as driver:
        browser=driver.chromium.launch(headless=True,executable_path=os.environ.get('JOURNEY_TEST_BROWSER'))
        try:run(browser,Path(folder).resolve())
        finally:browser.close()
