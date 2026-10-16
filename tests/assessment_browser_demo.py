"""Disposable Navigator assessment demo. Does not invoke server.main or workers.

Usage: python -B tests/assessment_browser_demo.py NODE_EXE PLAYWRIGHT_MODULE OUTPUT_DIR
The output directory receives synthetic receipts/screenshots, never source content.
"""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
from contextlib import closing
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mini_ark_server as bridge
from core import bounded_assessment as assessment
from core.placement import load_placement_doctrine


def main():
    node, playwright, output = sys.argv[1:]
    browser = Path(os.environ.get('BRAVE_EXECUTABLE', str(Path(os.environ.get('ProgramFiles', 'C:/Program Files'))/'BraveSoftware/Brave-Browser/Application/brave.exe')))
    if not browser.is_file():
        raise RuntimeError('Installed Brave required; set BRAVE_EXECUTABLE to its executable. No browser will be installed or substituted.')
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=True)
    repo = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='journey-assessment-demo-') as temp:
        root = Path(temp)
        source = root/'source'
        source.mkdir()
        for n in range(6):
            (source/str(n)).mkdir()
            (source/str(n)/'example.txt').write_text('synthetic unchanged metadata fixture')
        before = {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in source.rglob('*.txt')}
        doctrine = load_placement_doctrine(repo)
        location = dict(doctrine['locations'][0])
        location.update(id='fixture_pending_routing', path=str(source), aliases=[], legacy_aliases=[],
                        purpose='Synthetic pending routing', canonicality='transient_canonical')
        doctrine['locations'].append(location)
        (root/'config').mkdir()
        (root/'config'/'canonical_placement.json').write_text(json.dumps(doctrine))
        shutil.copy2(repo/'index.html', root/'index.html')
        for resource in bridge.PUBLIC_STATIC_PATHS:
            if resource == '/index.html':
                continue
            original = repo/resource.lstrip('/')
            if original.is_file():
                target = root/resource.lstrip('/')
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(original, target)
        db = root/'fixture.sqlite'
        with closing(sqlite3.connect(db)) as conn:
            conn.executescript('CREATE TABLE scans(id,root_path,started_at,completed_at,status,files_scanned,last_committed_path); CREATE TABLE files(canonical_path,size_bytes,last_seen_at);')
            from core.patrol_state import read_state
            read_state(conn)

        class Handler(bridge.Handler):
            def log_message(self, *args):
                pass

            def _get(self):
                # Unrelated startup panels are fixture responses; assessment POSTs
                # use the actual implementation and actual temporary SQLite ledger.
                if self.path.startswith('/api/'):
                    bridge._json_response(self, {'ok': True, 'actions': [], 'results': [], 'db': 'fixture'})
                else:
                    super()._get()

        def authorize(path):
            p = Path(path)
            return p == source or source in p.parents or p in source.parents

        script = r'''
const fs = require('fs');
const {chromium} = require(process.argv[1]);
(async () => {
  const browser = await chromium.launch({executablePath:process.argv[4], headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1280,height:1000}});
    const errors=[]; page.on('pageerror',e=>errors.push(e.message));
    await page.goto(process.argv[2]);
    await page.locator('[data-select="guide"]').first().click();
    await page.locator('[data-detail="guide-assessment"]').click();
    await page.locator('[data-run-action="assessment-status"]').last().click();
    await page.getByRole('button',{name:'Start Bounded Assessment'}).waitFor();
    await page.getByRole('button',{name:'Start Bounded Assessment'}).click();
    await page.getByRole('heading',{name:'Assessment #1: PENDING',exact:true}).waitFor();
    await page.getByRole('button',{name:'Continue Bounded Assessment'}).click();
    await page.getByRole('heading',{name:'Assessment #1: COMPLETE',exact:true}).waitFor();
    await page.getByRole('button',{name:'Refresh Evidence'}).click();
    await page.getByRole('heading',{name:'Assessment #1: COMPLETE',exact:true}).waitFor();
    await page.screenshot({path:process.argv[3]+'/desktop.png',fullPage:true});
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:process.argv[3]+'/mobile.png',fullPage:true});
    const receipt=await page.evaluate(async()=>{
      const r=await fetch('/api/actions/assessment-status',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
      if(!r.ok) throw new Error('receipt HTTP '+r.status);
      return r.json();
    });
    if(receipt.assessment.files!==6 || !receipt.assessment.coverage_complete) throw new Error('Incomplete receipt');
    if(errors.length) throw new Error(errors.join('\n'));
    fs.writeFileSync(process.argv[3]+'/receipt.json',JSON.stringify({fixture:true,browser:'Brave',browser_version:browser.version(),browser_errors:errors,...receipt},null,2));
    console.log('Brave Navigator: start -> PENDING -> continue -> COMPLETE -> retained receipt; six files');
    await page.locator('[data-select="manage"]').first().click();
    await page.locator('[data-detail="work-policy"]').click();
    await page.locator('[data-run-action="work-policy"]').last().click();
    await page.locator('#work-policy-intention').fill('Only help with duplicate detection and ask before every job');
    await page.getByRole('button',{name:'Review Request',exact:true}).click();
    await page.getByRole('heading',{name:'Requested, not applied: UNSUPPORTED',exact:true}).waitFor();
    const policyEvidence=await page.evaluate(async()=>{
      const post=async(name,body)=>(await fetch('/api/actions/'+name,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();
      const before=await post('work-policy',{});
      if(before.policy.posture.paused) throw new Error('Draft changed policy');
      const result=await post('patrol-control',{version:before.policy.posture.version,paused:true,reason:'Disposable fixture pause decision'});
      if(!result.ok) throw new Error('Fixture pause failed');
      return {before,after:await post('work-policy',{})};
    });
    await page.getByRole('button',{name:'Refresh Policy',exact:true}).click();
    await page.locator('#detail strong').filter({hasText:/^Paused$/}).waitFor();
    await page.screenshot({path:process.argv[3]+'/policy-mobile.png',fullPage:true});
    fs.writeFileSync(process.argv[3]+'/policy.json',JSON.stringify({fixture:true,...policyEvidence},null,2));
    if(errors.length) throw new Error(errors.join('\n'));
    console.log('Brave policy: shared persisted posture -> unsupported combined draft -> unchanged policy -> fixture pause -> refreshed Paused');
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1});
'''
        with patch.object(bridge, 'ROOT', root), patch.object(bridge, 'DB_PATH', db), \
             patch.object(bridge, 'ASSESSMENT_POLICY', {'scope': str(source), 'authorize': authorize}), \
             patch.object(assessment, 'require_path_not_held'):
            server = bridge.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                result = subprocess.run([node, '-e', script, playwright,
                                         f'http://127.0.0.1:{server.server_port}', str(output), str(browser)],
                                        capture_output=True, text=True, timeout=90)
                print(result.stdout)
                if result.returncode:
                    raise RuntimeError(result.stderr)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
        after = {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in source.rglob('*.txt')}
        assert before == after, 'Fixture source contents/mtimes changed'
        (output/'safety.json').write_text(json.dumps({'fixture': True, 'source_files': 6,
            'source_content_and_mtime_unchanged': True, 'production_services_touched': False,
            'production_scope_authorized': False, 'temporary_server_stopped': True}, indent=2))


if __name__ == '__main__':
    main()
