"""Foreground, checkpointed work toward an explicit user objective."""

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from threading import Event, Thread
from time import monotonic
from uuid import uuid4

from core.knowledge_contract import Need
from core.patrol import minimum_organization
from core.patrol_state import read_state, update_state
from journey_navigator.approval import WindowsApprover
from journey_navigator.guided import Guided
from journey_navigator.migrations import prepare_patrol_schema


SCHEMA = """
CREATE TABLE IF NOT EXISTS destinations (
 id TEXT PRIMARY KEY,job TEXT NOT NULL,objective TEXT NOT NULL,why TEXT NOT NULL,success TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'Not started',reason TEXT NOT NULL DEFAULT '',signature TEXT NOT NULL DEFAULT '',
 max_files INTEGER NOT NULL DEFAULT 20000,max_seconds INTEGER NOT NULL DEFAULT 300,updated TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS patrol_tasks (
 destination TEXT NOT NULL,kind TEXT NOT NULL,status TEXT NOT NULL,cursor INTEGER NOT NULL DEFAULT 0,
 attempts INTEGER NOT NULL DEFAULT 0,reason TEXT NOT NULL DEFAULT '',PRIMARY KEY(destination,kind));
CREATE TABLE IF NOT EXISTS patrol_assets (
 destination TEXT NOT NULL,asset INTEGER NOT NULL,record TEXT NOT NULL,PRIMARY KEY(destination,asset));
CREATE TABLE IF NOT EXISTS virtual_collections (
 destination TEXT NOT NULL,name TEXT NOT NULL,kind TEXT NOT NULL,PRIMARY KEY(destination,name));
CREATE TABLE IF NOT EXISTS virtual_memberships (
 destination TEXT NOT NULL,name TEXT NOT NULL,asset INTEGER NOT NULL,PRIMARY KEY(destination,name,asset));
CREATE TABLE IF NOT EXISTS patrol_questions (
 id TEXT PRIMARY KEY,destination TEXT NOT NULL,prompt TEXT NOT NULL,members TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'open',answer TEXT);
CREATE TABLE IF NOT EXISTS destination_outcomes (
 id INTEGER PRIMARY KEY,destination TEXT NOT NULL,binding TEXT NOT NULL,notes TEXT NOT NULL,
 authority TEXT NOT NULL,created TEXT DEFAULT CURRENT_TIMESTAMP);
"""
ACTIVE = ('Inspecting','Assessing','Working','Verifying')


class Patrol:
    def __init__(self, app, lock, *, approver=None):
        self.app, self.conn, self.lock = app, app.conn, lock
        prepare_patrol_schema(app)
        self.conn.executescript(SCHEMA)
        read_state(self.conn)
        with self.conn:
            self.conn.execute("UPDATE destinations SET state='Paused',reason='Restored checkpoint. Resume when ready.' WHERE state IN ('Inspecting','Assessing','Working','Verifying')")
            self.conn.execute("UPDATE patrol_tasks SET status='pending' WHERE status='running'")
        self.guided = Guided(app)
        self.approver = approver or WindowsApprover()
        self.stop = Event()
        self.wake = Event()
        self.started = {}
        self.start_counts = {}
        self.closed = False
        self.approval_threads = []
        self.worker = Thread(target=self._run, name='Journey foreground Patrol', daemon=False)
        self.worker.start()

    def close(self):
        if self.closed:
            return
        self.stop.set()
        self.wake.set()
        if hasattr(self.approver,'cancel'):
            self.approver.cancel()
        self.worker.join(timeout=20)
        if self.worker.is_alive():
            raise RuntimeError('Patrol is still completing its safe boundary.')
        for thread in self.approval_threads:
            thread.join(timeout=5)
        with self.lock:
            for row in self.conn.execute('SELECT id,state FROM destinations').fetchall():
                if row['state'] in ACTIVE:
                    self._state(row['id'],'Paused','Navigator closed at a safe checkpoint.')
            self.guided.close()
        self.closed = True

    def row(self, destination):
        row = self.conn.execute('SELECT * FROM destinations WHERE id=?',(destination,)).fetchone()
        if row is None:
            raise ValueError('Choose a saved Destination.')
        self.app._visible(self.app.job(row['job']))
        return row

    def _state(self, destination, state, reason=''):
        self.conn.execute('UPDATE destinations SET state=?,reason=?,updated=CURRENT_TIMESTAMP WHERE id=?',(state,reason,destination))
        self.conn.commit()

    def create(self, job, objective, why, success, max_files=20000, max_seconds=300):
        current = self.app.job(job)
        self.app._visible(current)
        if not self.app.retains or not all(isinstance(v,str) and 1<=len(v.strip())<=2000 for v in (objective,why,success)):
            raise ValueError('A retained inspection, objective, reason and success criterion are required.')
        if type(max_files) is not int or not 1<=max_files<=100000 or type(max_seconds) is not int or not 10<=max_seconds<=1800:
            raise ValueError('Choose a 1–100,000 entry ceiling and a 10–1,800 second foreground cycle.')
        destination = uuid4().hex
        with self.conn:
            self.conn.execute('INSERT INTO destinations(id,job,objective,why,success,max_files,max_seconds) VALUES(?,?,?,?,?,?,?)',
                              (destination,job,objective.strip(),why.strip(),success.strip(),max_files,max_seconds))
            self.conn.executemany("INSERT INTO patrol_tasks(destination,kind,status) VALUES(?,?,'pending')",[(destination,kind) for kind in ('inspect','assess')])
        return self.status(destination)

    def list(self):
        results=[]
        for row in self.conn.execute('SELECT id FROM destinations ORDER BY updated DESC').fetchall():
            try:
                results.append(self.status(row['id']))
            except (OSError,ValueError):
                continue
        return results

    def begin(self, destination, *, refresh=False):
        row=self.row(destination)
        state=read_state(self.conn)
        update_state(self.conn,version=state['version'],paused=False,reason='User began foreground Patrol')
        if refresh:
            self.app.refresh(row['job'])
            with self.conn:
                self.conn.execute("UPDATE patrol_tasks SET status='pending',cursor=0,attempts=0 WHERE destination=?",(destination,))
                self.conn.execute('DELETE FROM patrol_assets WHERE destination=?',(destination,))
                self.conn.execute('DELETE FROM virtual_memberships WHERE destination=?',(destination,))
        self.started[destination]=monotonic()
        baseline=self.app.summary(row['job'])
        self.start_counts[destination]=baseline['files']+baseline['folders']
        with self.conn:
            self.conn.execute("UPDATE patrol_tasks SET status='pending',attempts=0 WHERE destination=? AND status='failed'",(destination,))
        self._state(destination,'Inspecting')
        self.wake.set()
        return self.status(destination)

    def pause(self, destination):
        self.row(destination)
        state=read_state(self.conn)
        update_state(self.conn,version=state['version'],paused=True,reason='User paused foreground Patrol')
        self._state(destination,'Paused','Work stopped at a batch boundary.')
        with self.conn:
            self.conn.execute("UPDATE destinations SET state='Paused',reason='Patrol paused by the operator.' WHERE state IN ('Inspecting','Assessing','Working','Verifying')")
        self.app.pause()
        return self.status(destination)

    def signature(self, job):
        row=self.app.job(job)
        revision=self.conn.execute('SELECT max(id) FROM reviews WHERE job=?',(job,)).fetchone()[0]
        return sha256(json.dumps([row['epoch'],row['rule'],revision],sort_keys=True).encode()).hexdigest()

    def _assess(self, destination, row):
        task=self.conn.execute("SELECT * FROM patrol_tasks WHERE destination=? AND kind='assess'",(destination,)).fetchone()
        page=self.app.images(row['job'],task['cursor'],thumbnails=False)
        with self.conn:
            for image in page['items']:
                self.conn.execute('INSERT OR REPLACE INTO patrol_assets VALUES(?,?,?)',(destination,image['id'],json.dumps(image)))
                self.conn.execute('DELETE FROM virtual_memberships WHERE destination=? AND asset=?',(destination,image['id']))
                labels=[(value,'evidence-linked') for value in image['memberships']]
                matching=self.conn.execute("SELECT count(*) FROM files WHERE job=? AND epoch=? AND scope=? AND digest=? AND status='analyzed'",
                    (row['job'],self.app.job(row['job'])['epoch'],image['scope'],image['digest'])).fetchone()[0]
                if matching>1:
                    labels.append(('Identical image bytes '+image['digest'][:8],'content fingerprint'))
                if image['identity']['label'] and image['purpose']['label']:
                    labels.append((image['identity']['label']+' / '+image['purpose']['label'],'subject and purpose'))
                for name,kind in labels:
                    self.conn.execute('INSERT OR IGNORE INTO virtual_collections VALUES(?,?,?)',(destination,name,kind))
                    self.conn.execute('INSERT OR IGNORE INTO virtual_memberships VALUES(?,?,?)',(destination,name,image['id']))
            self.conn.execute("UPDATE patrol_tasks SET cursor=cursor+24,status=? WHERE destination=? AND kind='assess'",('pending' if page['more'] else 'complete',destination))
            if not page['more']:
                self.conn.execute('UPDATE destinations SET signature=? WHERE id=?',(self.signature(row['job']),destination))
                self._questions(destination)
        if not page['more']:
            self._finish(destination)

    def _questions(self, destination):
        groups={}
        for row in self.conn.execute('SELECT asset,record FROM patrol_assets WHERE destination=?',(destination,)):
            image=json.loads(row['record'])
            identity=image['identity']
            if identity['state']=='conflicting_evidence':
                labels=sorted(identity['conflicts'])
                key=image['scope']+'|'+str(labels)
                prompt='These images have competing identity clues: '+', '.join(labels)+'. Which subject fits the selected images?'
            elif image['name']['state']=='blocked':
                key=image['scope']+'|naming|'+image['name'].get('blocker','')
                prompt='These naming destinations need review: '+image['name'].get('blocker','')
            else:
                continue
            groups.setdefault(key,{'prompt':prompt,'members':[]})['members'].append(row['asset'])
        self.conn.execute("UPDATE patrol_questions SET state='superseded' WHERE destination=? AND state='open'",(destination,))
        for key,value in groups.items():
            identifier=sha256((destination+key).encode()).hexdigest()[:24]
            self.conn.execute("INSERT INTO patrol_questions(id,destination,prompt,members) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET members=excluded.members,state='open'",
                              (identifier,destination,value['prompt'],json.dumps(value['members'])))

    def _finish(self,destination):
        status=self.status(destination)
        state='Partially completed' if status['metrics']['unresolved'] or status['coverage']['skipped'] or status['coverage']['unsupported'] or status['coverage']['link_attention'] or any(task['status']=='failed' for task in status['tasks']) else 'Completed'
        if status['questions']:
            state='Awaiting clarification'
        if any(batch['status'] in ('blocked','failed','partially_completed') for batch in status['batches']):
            state='Partially completed'
        if status['batches_waiting']:
            state='Awaiting authorization'
        if status['outcome']:
            state='Completed'
        if any(batch['status']=='approved' for batch in status['batches']):
            state='Working'
        self._state(destination,state,'Eligible inspection and virtual organization have finished. Review the remaining questions and queued actions.')

    def cycle(self, destination):
        row=self.row(destination)
        if read_state(self.conn)['paused'] or row['state']=='Paused':
            return
        coverage=self.app.summary(row['job'])
        entries=coverage['files']+coverage['folders']-self.start_counts.get(destination,0)
        if monotonic()-self.started.get(destination,monotonic())>row['max_seconds'] or entries>row['max_files']:
            self._state(destination,'Partially completed','Resource budget reached. Resume for another bounded cycle.')
            return
        task=self.conn.execute("SELECT * FROM patrol_tasks WHERE destination=? AND status='pending' ORDER BY CASE kind WHEN 'inspect' THEN 0 ELSE 1 END LIMIT 1",(destination,)).fetchone()
        if task and task['kind']=='inspect':
            self._state(destination,'Inspecting','Inventory, local OCR and contextual analysis are continuing within this scope.')
            coverage=self.app.step(row['job'])
            if not coverage['pending'] and not coverage['pending_folders']:
                with self.conn:
                    self.conn.execute("UPDATE patrol_tasks SET status='complete' WHERE destination=? AND kind='inspect'",(destination,))
            return
        failed=self.conn.execute("SELECT 1 FROM patrol_tasks WHERE destination=? AND status='failed'",(destination,)).fetchone()
        if self.signature(row['job'])!=row['signature'] and not task and not failed:
            with self.conn:
                self.conn.execute("UPDATE patrol_tasks SET status='pending',cursor=0 WHERE destination=? AND kind='assess'",(destination,))
                self.conn.execute('DELETE FROM patrol_assets WHERE destination=?',(destination,))
                self.conn.execute('DELETE FROM virtual_memberships WHERE destination=?',(destination,))
            return
        if task:
            self._state(destination,'Assessing','Updating evidence-linked collections, naming work and grouped review questions.')
            self._assess(destination,row)
            return
        batch=self.guided.conn.execute("SELECT id FROM guided_batches WHERE job=? AND status='approved' ORDER BY created LIMIT 1",(row['job'],)).fetchone()
        if batch:
            self._state(destination,'Working','Executing the exact account-approved batch.')
            try:
                self.guided.step(batch['id'])
            except (OSError,ValueError) as error:
                with self.guided.conn:
                    self.guided.conn.execute("UPDATE guided_batches SET status='review_required',reason=? WHERE id=?",(str(error),batch['id']))
            self._state(destination,'Verifying','Recording verification and any operation that requires recovery.')
            return
        self._finish(destination)

    def _run(self):
        while not self.stop.is_set():
            self.wake.wait()
            self.wake.clear()
            while not self.stop.is_set():
                with self.lock:
                    rows=self.conn.execute("SELECT id FROM destinations WHERE state IN ('Inspecting','Assessing','Working','Verifying')").fetchall()
                    if not rows:
                        break
                    for row in rows:
                        if self.stop.is_set():
                            break
                        try:
                            self.cycle(row['id'])
                        except PermissionError as error:
                            self._state(row['id'],'Blocked',str(error))
                        except OSError as error:
                            task=self.conn.execute("SELECT * FROM patrol_tasks WHERE destination=? AND status='pending' ORDER BY kind DESC LIMIT 1",(row['id'],)).fetchone()
                            if task:
                                attempts=task['attempts']+1
                                with self.conn:
                                    self.conn.execute('UPDATE patrol_tasks SET attempts=?,status=?,reason=? WHERE destination=? AND kind=?',
                                        (attempts,'pending' if attempts<2 else 'failed',str(error),row['id'],task['kind']))
                                if attempts>=2:
                                    self._state(row['id'],'Assessing','A task reached its retry limit. Other eligible assessment continues.')
                            else:
                                self._state(row['id'],'Failed','A technical I/O failure stopped this cycle.')
                        except ValueError as error:
                            self._state(row['id'],'Blocked',str(error))
                        except Exception as error:
                            self._state(row['id'],'Failed',f'{type(error).__name__}: Patrol could not complete this checkpoint.')
                self.stop.wait(.03)

    def status(self,destination):
        row=self.row(destination)
        coverage=self.app.summary(row['job'])
        visible=set(self.app._visible(self.app.job(row['job'])))
        records=[]
        for value in self.conn.execute("""SELECT asset,json_extract(record,'$.path') AS path,json_extract(record,'$.scope') AS scope,
            json_extract(record,'$.identity.state') AS state FROM patrol_assets p JOIN files f ON f.id=p.asset
            WHERE p.destination=? AND f.job=? AND f.epoch=? AND f.status='analyzed'""",(destination,row['job'],self.app.job(row['job'])['epoch'])):
            image={'id':value['asset'],'path':value['path'],'scope':value['scope'],'identity':{'state':value['state']}}
            if image['scope'] not in visible:
                continue
            try:
                self.app.policy.check_image(Path(image['path']),retain=True)
            except PermissionError:
                continue
            records.append(image)
        allowed={image['id'] for image in records}
        states=Counter(image['identity']['state'] for image in records)
        questions=[dict(value) | {'members':json.loads(value['members'])} for value in self.conn.execute("SELECT id,prompt,members,state FROM patrol_questions WHERE destination=? AND state='open'",(destination,))]
        counts=Counter(name for name,asset in self.conn.execute('SELECT name,asset FROM virtual_memberships WHERE destination=?',(destination,)) if asset in allowed)
        collections=[{'name':name,'members':count} for name,count in counts.most_common()]
        questions=[question | {'members':[asset for asset in question['members'] if asset in allowed]} for question in questions]
        questions=[question for question in questions if question['members']]
        batches=[dict(value) for value in self.guided.conn.execute('SELECT id,status,reason FROM guided_batches WHERE job=? ORDER BY created DESC LIMIT 25',(row['job'],))]
        unresolved=sum(states.get(key,0) for key in ('unknown','conflicting_evidence','possibly_related','explicitly_rejected_identity'))
        receipts=self.guided.history(row['job'])
        tasks=[dict(task) for task in self.conn.execute('SELECT kind,status,cursor,attempts,reason FROM patrol_tasks WHERE destination=?',(destination,))]
        outcome_binding=sha256(json.dumps([row['objective'],row['success'],self.signature(row['job']),coverage['analyzed'],len(receipts)],sort_keys=True).encode()).hexdigest()
        outcome=self.conn.execute('SELECT * FROM destination_outcomes WHERE destination=? AND binding=? ORDER BY id DESC LIMIT 1',(destination,outcome_binding)).fetchone()
        need=Need(row['id'],row['objective'],row['why']).assess({key:True for key in ('capability','environment','resources','authority','policy','evidence')},
            outcome_verified=outcome is not None,evidence_refs=(f'owner-outcome:{outcome["id"]}',) if outcome else ())
        return dict(row) | {'coverage':coverage,'metrics':{'proposed':states['proposed_identity'],'confirmed':states['human_confirmed_identity'],
            'unresolved':unresolved,'collections':len(collections),'memberships':sum(value['members'] for value in collections),
            'physical_verified':sum(value['status']=='applied' for value in receipts)},'questions':questions,'collections':collections,
            'batches':batches,'batches_waiting':sum(value['status'] in ('review_required','authorizing') for value in batches),
            'need':need,'outcome_binding':outcome_binding,'outcome':dict(outcome) if outcome else None,
            'objective_outcome':'You accepted these results against the saved success criterion.' if outcome else 'Review the work against your saved success criterion. Activity and operation receipts do not establish subjective usefulness.',
            'tasks':tasks,'authority':{'capability':'Inspect, organize virtual collections, and Guided Patrol',
                'ceiling':'Exact account-approved batch','active':'Read and retain' if row['state']!='Working' else 'Exact approved operation',
                'scope':coverage['root']},'history':receipts}

    def answer(self,destination,ids,label,purpose,action='confirm'):
        row=self.row(destination)
        if not isinstance(ids,list) or not 1<=len(ids)<=50 or any(type(value) is not int for value in ids):
            raise ValueError('Select 1–50 images for a grouped correction.')
        for asset in ids:
            if not self.conn.execute('SELECT 1 FROM patrol_assets WHERE destination=? AND asset=?',(destination,asset)).fetchone():
                raise ValueError('The selected asset is outside this Destination.')
        for asset in ids:
            self.app.review(row['job'],asset,action,label,purpose)
        return self.begin(destination)

    def accept_outcome(self,destination,binding,notes):
        status=self.status(destination)
        if binding!=status['outcome_binding'] or status['state'] in ACTIVE or any(batch['status']=='authorizing' for batch in status['batches']):
            raise ValueError('The results are changing. Review the current completed cycle before accepting its outcome.')
        with self.conn:
            self.conn.execute('INSERT INTO destination_outcomes(destination,binding,notes,authority) VALUES(?,?,?,?)',
                (destination,binding,str(notes or 'The current result meets my saved success criterion.')[:2000],'Local operator outcome review'))
        self._state(destination,'Completed','The user accepted this result against the saved success criterion.')
        return self.status(destination)

    def images(self,destination,offset,collection='',assets=None):
        row=self.row(destination)
        selected=assets
        if collection:
            selected=[asset for asset, in self.conn.execute('SELECT asset FROM virtual_memberships WHERE destination=? AND name=?',(destination,collection))]
        page=self.app.images(row['job'],offset,asset_ids=selected)
        if selected and not page['items'] and row['state'] in ACTIVE:
            page['reason']='The inventory is refreshing. Review this group after the current assessment finishes.'
        return page

    def authorize(self,destination,batch):
        row=self.row(destination)
        if self.guided.conn.execute("SELECT 1 FROM guided_batches WHERE status='authorizing'").fetchone():
            raise ValueError('An account approval is already open. Finish or cancel that Windows dialog first.')
        if self.guided.row(batch)['job']!=row['job']:
            raise PermissionError('This batch belongs to another Destination.')
        binding,description=self.guided.begin_approval(batch)
        if row['state'] not in ACTIVE:
            self._state(destination,'Awaiting authorization','Review and authorize the exact batch in the Windows account dialog.')
        def request():
            try:
                consent=self.approver.verify(binding,description)
                with self.lock:
                    if self.stop.is_set():
                        raise PermissionError('Navigator closed. Approval was discarded.')
                    self.guided.accept(batch,consent)
                    self._state(destination,'Working','Account approval received for this exact batch.')
                    self.started[destination]=monotonic()
                    self.wake.set()
            except (OSError,ValueError) as error:
                with self.lock:
                    if not self.stop.is_set():
                        with self.guided.conn:
                            self.guided.conn.execute("UPDATE guided_batches SET status='review_required',reason=? WHERE id=?",(str(error),batch))
                        self._state(destination,'Awaiting authorization',str(error))
        thread=Thread(target=request,name='Journey account approval',daemon=True)
        thread.start()
        self.approval_threads.append(thread)
        return {'requested':True,'binding':binding}

    def suggested_batch(self,destination,ids):
        row=self.row(destination)
        if not isinstance(ids,list) or not 1<=len(ids)<=20:
            raise ValueError('Select 1–20 naming proposals.')
        operations=[]
        for asset in ids:
            saved=self.conn.execute('SELECT record FROM patrol_assets WHERE destination=? AND asset=?',(destination,asset)).fetchone()
            if not saved:
                raise ValueError('Choose a current naming proposal.')
            image=json.loads(saved['record'])
            if image['name']['state']!='proposed':
                raise ValueError('A confirmed subject and purpose are needed for a physical naming proposal.')
            target=Path(image['path']).with_name(Path(image['name']['destination']).name)
            operations.append({'kind':'rename','asset':asset,'destination':str(target),
                'reason':image['name']['reason']+' Retains the current physical parent folder.'})
        result=self.guided.prepare(row['job'],operations)
        return result
