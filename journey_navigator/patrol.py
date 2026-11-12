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
from journey_navigator.stewardship import Stewardship


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
CREATE TABLE IF NOT EXISTS patrol_evidence_checkpoint (
 destination TEXT PRIMARY KEY, base TEXT NOT NULL, history INTEGER NOT NULL,
 mode TEXT NOT NULL DEFAULT 'full', reassessed INTEGER NOT NULL DEFAULT 0, reused INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS patrol_evidence_queue (
 destination TEXT NOT NULL,asset INTEGER NOT NULL,PRIMARY KEY(destination,asset));
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
            self.conn.execute("INSERT OR IGNORE INTO patrol_tasks(destination,kind,status) SELECT id,'reconcile','pending' FROM destinations")
        self.guided = Guided(app)
        from journey_navigator.duplicates import DuplicatePatrol
        self.duplicates = DuplicatePatrol(self)
        self.stewardship = Stewardship(self)
        from journey_navigator.capabilities import Capabilities
        from journey_navigator.watch import DriftWatch
        self.capabilities = Capabilities(self)
        self.watch = DriftWatch(app)
        self.guided.retirement_guard = self.stewardship.verify_archive
        self.approver = approver or WindowsApprover()
        self.stop = Event()
        self.wake = Event()
        self.started = {}
        self.start_counts = {}
        self.closed = False
        self.history_due = 0
        self.approval_threads = []
        # Upgrade an already completed checkpoint without reinterpreting its assets.
        with self.conn:
            for saved in self.conn.execute("SELECT id,job,signature FROM destinations WHERE signature<>''").fetchall():
                complete = not self.conn.execute("SELECT 1 FROM patrol_tasks WHERE destination=? AND status<>'complete'", (saved['id'],)).fetchone()
                if complete and saved['signature'] == self.signature(saved['job']):
                    self.conn.execute("INSERT OR IGNORE INTO patrol_evidence_checkpoint(destination,base,history,mode) VALUES(?,?,?,'complete')",
                        (saved['id'], self.signature(saved['job'], include_history=False), self.app.history.change_cursor(saved['job'])))
        self.worker = Thread(target=self._run, name='Journey foreground Patrol', daemon=False)
        self.worker.start()
        self.wake.set()

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
            self.duplicates.grants.clear();self.duplicates.watches.clear();self.duplicates.pending_audits.clear()
            self.stewardship.clear()
            self.watch.stop()
            with self.conn:
                self.app.history.pause()
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
            self.conn.executemany("INSERT INTO patrol_tasks(destination,kind,status) VALUES(?,?,'pending')",
                                  [(destination,kind) for kind in ('inspect','duplicates','reconcile','assess')])
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
                self.conn.execute('DELETE FROM patrol_evidence_checkpoint WHERE destination=?',(destination,))
                self.conn.execute('DELETE FROM patrol_evidence_queue WHERE destination=?',(destination,))
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
            self.app.history.pause()
        self.duplicates.pending_audits.clear()
        self.duplicates.watches.clear()
        self.watch.stop('paused')
        self.app.pause()
        return self.status(destination)

    def signature(self, job, *, include_history=True):
        row=self.app.job(job)
        revision=self.conn.execute('SELECT max(id) FROM reviews WHERE job=?',(job,)).fetchone()[0]
        profile = self.app.project_registry.profile(job)
        knowledge = [profile['revision'], profile['knowledge_version']] if profile else None
        retirements = self.conn.execute('SELECT max(id) FROM stewardship_retirements WHERE job=?',(job,)).fetchone()[0]
        audit = self.app.project_audit.binding(job)
        history = self.app.history.binding(job) if include_history else None
        return sha256(json.dumps(['integrated-pilot',row['epoch'],row['rule'],revision,knowledge,retirements,audit,history],sort_keys=True).encode()).hexdigest()

    def _assess(self, destination, row, *, background=False):
        task=self.conn.execute("SELECT * FROM patrol_tasks WHERE destination=? AND kind='assess'",(destination,)).fetchone()
        binding = self.signature(row['job'])
        if task['cursor'] and binding != row['signature']:
            self._reset_assessment(destination)
            return
        if not task['cursor']:
            with self.conn:
                self.conn.execute('UPDATE destinations SET signature=? WHERE id=?',(binding,destination))
        checkpoint = self.conn.execute('SELECT * FROM patrol_evidence_checkpoint WHERE destination=?', (destination,)).fetchone()
        selective = checkpoint is not None and checkpoint['mode'] == 'incremental'
        selected = [item[0] for item in self.conn.execute('SELECT asset FROM patrol_evidence_queue WHERE destination=? ORDER BY asset LIMIT 24', (destination,))] if selective else None
        page=self.app.images(row['job'], 0 if selective else task['cursor'], thumbnails=False, asset_ids=selected)
        if selective:
            page['more'] = self.conn.execute('SELECT count(*) FROM patrol_evidence_queue WHERE destination=?', (destination,)).fetchone()[0] > len(selected)
        with self.conn:
            if selective:
                self.conn.executemany('DELETE FROM patrol_evidence_queue WHERE destination=? AND asset=?', ((destination, asset) for asset in selected))
                self.conn.execute('UPDATE patrol_evidence_checkpoint SET reassessed=reassessed+? WHERE destination=?', (len(page['items']), destination))
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
                if selective:
                    self.conn.execute("UPDATE patrol_evidence_checkpoint SET mode='complete' WHERE destination=?", (destination,))
                else:
                    self.conn.execute("INSERT OR REPLACE INTO patrol_evidence_checkpoint(destination,base,history,mode,reassessed,reused) VALUES(?,?,?,'complete',?,0)",
                        (destination, self.signature(row['job'], include_history=False), self.app.history.change_cursor(row['job']),
                         self.conn.execute('SELECT count(*) FROM patrol_assets WHERE destination=?', (destination,)).fetchone()[0]))
                self._questions(destination)
        if background:
            self._state(destination, 'Partially completed', 'Historical evidence updated within the monitored scope. Review the refreshed virtual groups and remaining questions.')
        elif not page['more']:
            self._finish(destination)

    def _reset_assessment(self, destination):
        row = self.row(destination)
        checkpoint = self.conn.execute('SELECT * FROM patrol_evidence_checkpoint WHERE destination=?', (destination,)).fetchone()
        base = self.signature(row['job'], include_history=False)
        selective = checkpoint is not None and checkpoint['base'] == base
        with self.conn:
            self.conn.execute("UPDATE patrol_tasks SET status='pending',cursor=0 WHERE destination=? AND kind IN ('reconcile','assess')", (destination,))
            if selective:
                affected = self.app.history.affected_since(row['job'], checkpoint['history'])
                self.conn.executemany('INSERT OR IGNORE INTO patrol_evidence_queue VALUES(?,?)', ((destination, asset) for asset in affected))
                total = self.conn.execute('SELECT count(*) FROM patrol_assets WHERE destination=?', (destination,)).fetchone()[0]
                # Stamp the new evidence before processing so an interrupted queue can resume.
                self.conn.execute("UPDATE patrol_evidence_checkpoint SET history=?,mode='incremental',reassessed=0,reused=? WHERE destination=?",
                    (self.app.history.change_cursor(row['job']), max(0, total-self.conn.execute('SELECT count(*) FROM patrol_evidence_queue WHERE destination=?', (destination,)).fetchone()[0]), destination))
                self.conn.execute('UPDATE destinations SET signature=? WHERE id=?', (self.signature(row['job']), destination))
            else:
                self.conn.execute('DELETE FROM patrol_evidence_checkpoint WHERE destination=?', (destination,))
                self.conn.execute('DELETE FROM patrol_evidence_queue WHERE destination=?', (destination,))
                self.conn.execute('DELETE FROM patrol_assets WHERE destination=?',(destination,))
                self.conn.execute('DELETE FROM virtual_memberships WHERE destination=?',(destination,))

    def _questions(self, destination):
        groups={}
        for row in self.conn.execute('SELECT asset,record FROM patrol_assets WHERE destination=?',(destination,)):
            image=json.loads(row['record'])
            identity=image['identity']
            if identity['state']=='conflicting_evidence':
                labels=sorted(identity['conflicts'])
                key=image['scope']+'|'+str(labels)
                prompt='These images have competing identity clues: '+', '.join(labels)+'. Which subject fits the selected images?'
            elif image['purpose']['state']=='conflicting_evidence':
                labels=sorted(image['purpose'].get('conflicts', []))
                key=image['scope']+'|purpose|'+str(labels)
                prompt='Which purpose fits this group? The evidence suggests '+', '.join(labels)+'.'
            elif image['name']['state'] in ('blocked', 'needs_date'):
                reason=image['name'].get('blocker') or image['name']['reason']
                key=image['scope']+'|naming|'+reason
                prompt='These naming destinations need review. '+reason
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
        if monotonic()-self.started.get(destination,monotonic())>row['max_seconds']:
            self._state(destination,'Partially completed','Resource budget reached. Resume for another bounded cycle.')
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
        if entries>row['max_files']:
            self._state(destination,'Partially completed','Inspection entry budget reached. Resume for another bounded cycle.')
            return
        task=self.conn.execute("SELECT * FROM patrol_tasks WHERE destination=? AND status='pending' ORDER BY CASE kind WHEN 'inspect' THEN 0 WHEN 'duplicates' THEN 1 WHEN 'reconcile' THEN 2 ELSE 3 END LIMIT 1",(destination,)).fetchone()
        checkpoint = self.conn.execute('SELECT base FROM patrol_evidence_checkpoint WHERE destination=?', (destination,)).fetchone()
        if checkpoint and row['signature'] != self.signature(row['job']) and not (task and task['kind'] == 'inspect'):
            self._reset_assessment(destination)
            return
        if task and task['kind']=='inspect':
            self._state(destination,'Inspecting','Inventory, local OCR and contextual analysis are continuing within this scope.')
            coverage=self.capabilities.inspect(row['job'])
            if not coverage['pending'] and not coverage['pending_folders']:
                with self.conn:
                    self.conn.execute("UPDATE patrol_tasks SET status='complete' WHERE destination=? AND kind='inspect'",(destination,))
            return
        if task and task['kind']=='duplicates':
            self._state(destination,'Assessing','Auditing exact duplicates before organization. No deletion permission is implied.')
            if self.duplicates.audit_step(row['job']):
                result=self.duplicates.status(row['job'])['audit']
                with self.conn:self.conn.execute("UPDATE patrol_tasks SET status='complete',reason=? WHERE destination=? AND kind='duplicates'",
                    (f"{result['proposed_removals']} exact redundant-copy candidates; near variants retained for review.",destination))
            return
        if task and task['kind']=='reconcile':
            profile = self.app.project_registry.profile(row['job'])
            result = self.capabilities.reconcile(row['job']) if profile else None
            reason = (f"{result['name_candidates']} reference name matches in the current root."
                      if result else 'No active project profile. Generic inspection remains available.')
            with self.conn:
                self.conn.execute("UPDATE patrol_tasks SET status='complete',reason=? WHERE destination=? AND kind='reconcile'",(reason,destination))
            return
        failed=self.conn.execute("SELECT 1 FROM patrol_tasks WHERE destination=? AND status='failed'",(destination,)).fetchone()
        if self.signature(row['job'])!=row['signature'] and not task and not failed:
            self._reset_assessment(destination)
            return
        if task:
            self._state(destination,'Assessing','Updating evidence-linked collections, naming work and grouped review questions.')
            self._assess(destination,row)
            return
        self._finish(destination)

    def _background_history(self):
        history = self.app.history
        if not history.monitor or monotonic() < self.history_due or read_state(self.conn)['paused']:
            return
        job = history.monitor[0]
        if self.conn.execute("SELECT 1 FROM history_sources WHERE job=? AND status='queued'", (job,)).fetchone():
            return
        self.history_due = monotonic() + 60
        # Read-only virtual updates use a separate route that cannot execute batches.
        for row in self.conn.execute("""SELECT d.* FROM destinations d JOIN patrol_evidence_checkpoint c ON c.destination=d.id
                WHERE d.job=? AND d.state IN ('Completed','Partially completed','Awaiting clarification','Awaiting authorization')
                ORDER BY d.updated,d.id""", (job,)).fetchall():
            checkpoint = self.conn.execute('SELECT * FROM patrol_evidence_checkpoint WHERE destination=?', (row['id'],)).fetchone()
            if checkpoint['base'] != self.signature(job, include_history=False):
                continue  # Profile, file or operator-decision changes require ordinary Patrol review.
            if row['signature'] != self.signature(job):
                self._reset_assessment(row['id'])
                row = self.row(row['id'])
            elif checkpoint['mode'] != 'incremental':
                continue
            self._assess(row['id'], row, background=True)
            return  # At most one 24-asset page per minute, across all saved Destinations.

    def _run(self):
        while not self.stop.is_set():
            deadlines = ([self.watch.due] if self.watch.target else []) + ([self.app.history.monitor_due, max(self.history_due, monotonic() + 1)] if self.app.history.monitor else [])
            if self.duplicates.watches:deadlines.append(self.duplicates.due)
            self.wake.wait(timeout=max(0, min(deadlines) - monotonic()) if deadlines else None)
            self.wake.clear()
            while not self.stop.is_set():
                with self.lock:
                    rows=self.conn.execute("SELECT id FROM destinations WHERE state IN ('Inspecting','Assessing','Working','Verifying')").fetchall()
                    self.watch.tick()
                    self.duplicates.tick()
                    self.app.history.monitor_tick()
                    auditing = self.duplicates.advance()
                    reading = self.capabilities.history_step()
                    try:
                        self._background_history()
                    except (OSError, ValueError):
                        self.app.history.monitor_stop()
                    if not rows and not reading and not auditing:
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
            json_extract(record,'$.identity.state') AS state,json_extract(record,'$.purpose.state') AS purpose
            FROM patrol_assets p JOIN files f ON f.id=p.asset
            WHERE p.destination=? AND f.job=? AND f.epoch=? AND f.status='analyzed'""",(destination,row['job'],self.app.job(row['job'])['epoch'])):
            image={'id':value['asset'],'path':value['path'],'scope':value['scope'],'identity':{'state':value['state']},
                   'purpose':value['purpose']}
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
        unresolved = sum(image['identity']['state'] in ('unknown','conflicting_evidence','possibly_related','explicitly_rejected_identity')
                         or image['purpose'] in ('unknown','conflicting_evidence') for image in records)
        receipts=self.guided.history(row['job'])
        tasks=[dict(task) for task in self.conn.execute('SELECT kind,status,cursor,attempts,reason FROM patrol_tasks WHERE destination=?',(destination,))]
        current_signature = self.signature(row['job'])
        outcome_binding=sha256(json.dumps([row['objective'],row['success'],current_signature,coverage['analyzed'],len(receipts)],sort_keys=True).encode()).hexdigest()
        outcome=self.conn.execute('SELECT * FROM destination_outcomes WHERE destination=? AND binding=? ORDER BY id DESC LIMIT 1',(destination,outcome_binding)).fetchone()
        reviewed = sum(value['status']=='applied' for value in receipts)
        waiting = sum(value['status'] in ('review_required','authorizing') for value in batches)
        result = (f"{coverage['analyzed']} images assessed, {len(collections)} virtual groups, and {reviewed} verified operations. "
                  f"{coverage['pending']} images and {coverage['pending_folders']} folders waiting. "
                  f"{unresolved} unresolved assets, {coverage['skipped']} skipped entries, "
                  f"{coverage['link_attention']} links needing review, and {waiting} batches awaiting approval. "
                  + ('Outcome accepted for this snapshot.' if outcome else 'Outcome review remains open.'))
        reconciliation = next((task['reason'] for task in tasks if task['kind']=='reconcile' and task['status']=='complete'), '')
        if reconciliation:
            result += ' ' + reconciliation
        if row['signature'] and row['signature'] != current_signature:
            result += ' Evidence changed. Resume Patrol for a fresh assessment.'
        need=Need(row['id'],row['objective'],row['why']).assess({key:True for key in ('capability','environment','resources','authority','policy','evidence')},
            outcome_verified=outcome is not None,evidence_refs=(f'owner-outcome:{outcome["id"]}',) if outcome else ())
        checkpoint = self.conn.execute('SELECT mode,reassessed,reused,history FROM patrol_evidence_checkpoint WHERE destination=?', (destination,)).fetchone()
        if checkpoint:
            result += f" Evidence update reassessed {checkpoint['reassessed']} assets and reused {checkpoint['reused']} saved assessments."
        return dict(row) | {'incremental': dict(checkpoint) if checkpoint else None, 'coverage':coverage,'inspection_epoch':self.app.job(row['job'])['epoch'],'metrics':{'proposed':states['proposed_identity'],'confirmed':states['human_confirmed_identity'],
            'unresolved':unresolved,'collections':len(collections),'memberships':sum(value['members'] for value in collections),
            'physical_verified':reviewed},'questions':questions,'collections':collections,
            'batches':batches,'batches_waiting':waiting,'report':result,
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
        if (binding!=status['outcome_binding'] or status['state'] in ACTIVE
                or status['signature'] != self.signature(status['job'])
                or any(task['status'] in ('pending', 'running') for task in status['tasks'])
                or any(batch['status']=='authorizing' for batch in status['batches'])):
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

    def authorize_duplicate_permission(self, job, automatic=False):
        if any(t.is_alive() for t in self.approval_threads) or self.guided.conn.execute("SELECT 1 FROM guided_batches WHERE status='authorizing'").fetchone():
            raise ValueError('Finish the current account approval first.')
        binding,description=self.duplicates.grant_preview(job,automatic)
        def request():
            try:
                consent=self.approver.verify(binding,description)
                with self.lock:
                    if self.stop.is_set():raise PermissionError('Navigator closed; scope permission was discarded.')
                    self.duplicates.activate(binding,consent)
            except (OSError,ValueError) as error:
                with self.lock:
                    self.duplicates.revoke(job);self.duplicates.audit_errors[job]=str(error)
        thread=Thread(target=request,name='Journey scoped duplicate permission',daemon=False)
        self.approval_threads.append(thread);thread.start()
        return {'state':'awaiting_account_permission','scope':self.app.job(job)['root']}

    def duplicate_destination(self, job):
        self.duplicates.scope(job)
        row=self.conn.execute('SELECT id FROM destinations WHERE job=? ORDER BY updated DESC LIMIT 1',(job,)).fetchone()
        if row:return row[0]
        return self.create(job,'Maintain exact duplicates in this approved collection',
            'Reduce redundant copies while preserving distinct assets and known dependencies',
            'Reviewed recoverable cleanup and a current duplicate inventory')['id']

    def authorize(self,destination,batch):
        row=self.row(destination)
        if any(t.is_alive() for t in self.approval_threads) or self.guided.conn.execute("SELECT 1 FROM guided_batches WHERE status='authorizing'").fetchone():
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
        current={image['id']:image for image in self.app.images(row['job'],0,asset_ids=ids,thumbnails=False)['items']}
        operations=[]
        for asset in ids:
            image=current.get(asset)
            if not image:
                raise ValueError('Choose a current naming proposal.')
            if image['name']['state']!='proposed':
                raise ValueError(image['name'].get('blocker') or 'A confirmed subject, purpose and validated project convention are needed for a physical naming proposal.')
            target=Path(image['path']).with_name(Path(image['name']['destination']).name)
            operations.append({'kind':'rename','asset':asset,'destination':str(target),
                'reason':image['name']['reason']+' Retains the current physical parent folder.'})
        result=self.guided.prepare(row['job'],operations)
        return result
