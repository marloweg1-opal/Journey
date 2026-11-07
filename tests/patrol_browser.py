"""Browser acceptance uses a declared test approver and the real executor."""

from contextlib import contextmanager, closing
import json
import os
from pathlib import Path
import sys
import sqlite3
import shutil
from tempfile import TemporaryDirectory
from threading import Thread

from playwright.sync_api import expect,sync_playwright

from journey_navigator.__main__ import Navigator
from journey_navigator.workbench import Workbench
from navigator_fixtures import make_link
from test_navigator_context import make_board, reader
from test_operational_patrol import FixtureConsent


@contextmanager
def navigator(data, policy):
    app=Workbench(data,ocr=reader(),hold_store=policy)
    try:
        with Navigator(app,approver=FixtureConsent()) as server:
            worker=Thread(target=server.serve_forever)
            worker.start()
            try:
                yield server
            finally:
                server.shutdown();worker.join()
    finally:
        app.close()


def run(browser,base):
    source=base/'CareBloomOS';source.mkdir()
    for index in range(30):
        make_board(source/f'Moonstone reference sheet v{index:02}.png',variation=index)
    outside=base/'Outside project';outside.mkdir()
    make_board(outside/'Cloverstone.png','Cloverstone')
    make_link(source/'Outside shortcut.lnk',outside)
    make_link(source/'Loop junction',source,'junction')
    for name in ('Moonstone','Cloverstone','Cloudstone'):
        (source/name).mkdir()
    make_board(source/'Moonstone'/'untitled.png','Moonstone','Character reference sheet')
    make_board(source/'Cloudstone'/'untitled-cloud.png','Cloudstone','Character reference sheet')
    for number in (1,2):
        make_board(source/'Cloverstone'/f'Moonstone misleading v0{number}.png','Cloverstone','Character reference sheet',variation=number)
    make_board(source/'Cloverstone'/'Cloverstone original.png','Cloverstone','Concept board')
    shutil.copyfile(source/'Cloverstone'/'Cloverstone original.png',source/'Cloverstone'/'duplicate.png')
    nested=source/'Heartstone'/'Variations';nested.mkdir(parents=True)
    make_board(nested/'unclear.png','Wishstone','Character reference sheet')
    (source/'Occupied name.png').write_bytes(b'occupied destination fixture')
    held=source/'Held material';held.mkdir()
    make_board(held/'Held sample.png','Moonstone')
    policy=base/'source-policy.sqlite'
    with closing(sqlite3.connect(policy)) as store:
        store.execute('CREATE TABLE media_source_holds(scope TEXT,reason TEXT)')
        store.execute('INSERT INTO media_source_holds VALUES(?,?)',(str(held),'Fixture source hold'))
        store.commit()
    data=base/'Saved Journey'
    errors=[]
    with navigator(data,policy) as server:
        page=browser.new_page()
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(server.url)
        expect(page.get_by_text('Journey 0.4.0 Guided Patrol',exact=False)).to_be_visible()
        page.get_by_label('Keep a local checkpoint',exact=False).check()
        page.get_by_label('Suggest names and draft a plan',exact=True).check()
        page.get_by_label('Folder or shortcut path').fill(str(source))
        page.get_by_role('button',name='Inspect selection',exact=True).click()
        expect(page.locator('[data-count="analyzed"]')).to_have_text('37',timeout=90000)
        page.locator('.journey-tools').get_by_role('button',name='Destination',exact=True).click()
        page.get_by_label('Why this matters',exact=True).fill('I need to retrieve and continue this artwork.')
        page.get_by_role('button',name='Save Destination',exact=True).click()
        page.get_by_role('button',name='Begin or resume Patrol',exact=True).click()
        expect(page.locator('#patrol-state')).to_have_text('Awaiting clarification',timeout=60000)
        expect(page.locator('#patrol-collections')).to_contain_text('Moonstone')
        expect(page.locator('#patrol-metrics')).to_contain_text('37')
        page.get_by_role('button',name='Open Review',exact=True).click()
        page.get_by_text('Review a folder creation or within-scope move',exact=True).click()
        folder=source/'Curated References'
        form=page.locator('#patrol-operation')
        form.get_by_label('Exact destination path').fill(str(folder))
        form.get_by_label('Reason this improves the collection').fill('Create a deliberate destination for curated reference exports.')
        form.get_by_role('button',name='Prepare exact batch').click()
        expect(page.locator('#patrol-batch-details')).to_contain_text(str(folder))
        assert not folder.exists()
        page.get_by_role('button',name='Authorize exact batch with my Windows account').click()
        expect(page.locator('#patrol-history')).to_contain_text('directory_create',timeout=30000)
        assert folder.is_dir()
        # Group a correction, then get an actual contextual rename proposal.
        page.get_by_role('button',name='Select these images',exact=True).first.click()
        expect(page.locator('.patrol-asset:checked')).to_have_count(2)
        answer=page.locator('#patrol-answer')
        answer.get_by_label('Identity',exact=True).fill('Cloverstone')
        answer.get_by_label('Purpose',exact=True).fill('Character Reference')
        answer.get_by_role('button',name='Apply grouped correction').click()
        expect(page.locator('#patrol-state')).to_have_text('Awaiting clarification',timeout=30000)
        page.locator('.journey-tools').get_by_role('button',name='Review',exact=True).click()
        expect(page.locator('.patrol-name').first).to_be_visible(timeout=15000)
        if os.name=='nt':
            page.locator('.patrol-name').first.check()
            page.get_by_role('button',name='Review selected naming changes').click()
            expect(page.locator('#patrol-batch-details')).to_contain_text('rename')
            page.get_by_role('button',name='Authorize exact batch with my Windows account').click()
            expect(page.locator('#patrol-history')).to_contain_text('file_move',timeout=30000)
            page.get_by_role('button',name='Review safe reversal').first.click()
            expect(page.locator('#patrol-batch-details')).to_contain_text('undo')
            page.get_by_role('button',name='Authorize exact batch with my Windows account').click()
            expect(page.locator('#patrol-history')).to_contain_text('undo:file_move',timeout=30000)
        screenshot=os.environ.get('JOURNEY_ACCEPTANCE_SCREENSHOT')
        if screenshot:
            page.screenshot(path=screenshot,full_page=True)
        assert (outside/'Cloverstone.png').exists()
        assert not list(outside.glob('Curated*'))
        print('Browser completed real journaled folder creation, grouped correction, virtual collection work, and '+('real rename and reversal.' if os.name=='nt' else 'Windows execution withheld on this host.'))
        print('Approval actor was the declared automated fixture actor. Native human account verification remains a separate owner acceptance step.')
        page.close()
    assert not errors,errors


def main():
    with TemporaryDirectory(prefix='journey-patrol-browser-') as temporary,sync_playwright() as playwright:
        options={'headless':True}
        if os.environ.get('JOURNEY_CHROMIUM'):
            options['executable_path']=os.environ['JOURNEY_CHROMIUM']
            options['args']=['--no-sandbox']
        browser=playwright.chromium.launch(**options)
        try: run(browser,Path(temporary).resolve())
        finally: browser.close()


if __name__=='__main__':main()
