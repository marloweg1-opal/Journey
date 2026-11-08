"""Guided batches adapt account-verified approval to Journey's existing executor."""

from dataclasses import asdict
from hashlib import sha256
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
from uuid import uuid4

from core import apply as executor
from core.circuit_breaker import check_operation_magnitude
from core.file_paths import safe_metadata, signature
from core.move_evidence import MoveEvidence, MoveEvidenceDenied, MoveEvidenceVerifier, MoveIdentity, approval_binding
from core.patrol_state import read_state
from core.recovery_inspection import file_identity, inspect_operation
from db.database import initialize_schema
from journey_navigator.session import protect
from journey_navigator.context import require_preserved_filename
from journey_planner.catalog import component


MAX_BATCH = 20
EXPIRY = 600
SCHEMA = """
CREATE TABLE IF NOT EXISTS guided_batches (
 id TEXT PRIMARY KEY,job TEXT NOT NULL,scope TEXT NOT NULL,payload TEXT NOT NULL,binding TEXT NOT NULL,
 status TEXT NOT NULL,approval TEXT,proof TEXT,proposal INTEGER,reason TEXT NOT NULL DEFAULT '',created TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS guided_operations (
 batch TEXT NOT NULL,position INTEGER NOT NULL,item INTEGER,receipt INTEGER,status TEXT NOT NULL DEFAULT 'pending',
 reason TEXT NOT NULL DEFAULT '',PRIMARY KEY(batch,position));
"""


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def receipt_binding(row):
    fields=('id','action_type','target_path','previous_state','new_state','performed_at')
    return sha256(encoded({key:row[key] for key in fields}).encode()).hexdigest()


class GuidedVerifier(MoveEvidenceVerifier):
    def __init__(self, owner, batch):
        self.owner, self.batch = owner, batch

    def guard_path(self, path):
        self.owner.guard(self.batch, path)

    def verify(self, conn, item, *, phase):
        batch, payload, approval = self.owner.authorized(self.batch)
        operation = next((op for op in payload['operations'] if op.get('item') == item['id']), None)
        if operation is None or operation['kind'] not in ('rename', 'move'):
            raise MoveEvidenceDenied('This operation is absent from the account-approved batch')
        self.owner.validate_operation(batch, operation, source=True)
        return MoveEvidence(receipt_id=batch['id'], approval_reference=approval['account'],
            approval_binding=approval['proposal_binding'],
            evidence_references=(f"account-verified-dependency-disposition:{batch['binding']}",),
            proposal_id=batch['proposal'],item_id=item['id'],source=operation['source'],destination=operation['destination'],
            source_scope=batch['scope'],destination_scope=batch['scope'],identity=MoveIdentity(**operation['identity']),
            issued_at=approval['verified_at'],expires_at=approval['expires_at'])


class Guided:
    def __init__(self, workbench):
        self.workbench = workbench
        self.conn = sqlite3.connect(workbench.data_dir / 'navigator-actions.sqlite', check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        initialize_schema(self.conn)
        self.conn.executescript(SCHEMA)
        path = workbench.data_dir / 'guided-approval-key.dat'
        if path.exists():
            safe_metadata(path)
            self.key = protect(path.read_bytes(), decrypt=True)
        else:
            self.key = secrets.token_bytes(32)
            with path.open('xb') as output:
                output.write(protect(self.key))
                output.flush()
                os.fsync(output.fileno())
            os.chmod(path, 0o600)
        with self.conn:
            self.conn.execute("UPDATE guided_batches SET status='review_required',approval=NULL,proof=NULL,reason='Session restarted. Review and authorize remaining work again.' WHERE status IN ('authorizing','approved','working')")
            self.conn.execute("UPDATE proposals SET status='pending' WHERE id IN (SELECT proposal FROM guided_batches WHERE status='review_required')")

    def close(self):
        self.conn.close()

    def row(self, batch):
        row = self.conn.execute('SELECT * FROM guided_batches WHERE id=?', (batch,)).fetchone()
        if row is None:
            raise ValueError('Choose a reviewed batch.')
        return row

    def guard(self, batch_id, path):
        batch = self.row(batch_id)
        app = self.workbench
        app.policy.refresh()
        app._validate_scope(app.job(batch['job']), batch['scope'])
        if read_state(app.conn)['paused']:
            raise PermissionError('Patrol is paused.')
        path, scope = Path(path), Path(batch['scope'])
        if not (path.is_relative_to(scope) or scope.is_relative_to(path)):
            raise PermissionError('This path is outside the reviewed execution scope.')
        app.policy.check(path)
        if os.name=='nt' and Path(r'C:\mini_ark\ARK_EXECUTION_DISABLED.flag').exists():
            raise PermissionError('The existing Journey execution kill switch is active.')
        registry = app.policy.perception_store
        for query, table in (("SELECT path FROM protected_paths", 'protected_paths'),
                             ("SELECT canonical_path FROM file_dependents WHERE active=1", 'file_dependents')):
            for protected, in app.policy._rows(registry, query, table, optional_table=True):
                if path == Path(protected) or (table == 'protected_paths' and path.is_relative_to(protected)):
                    raise PermissionError('An existing Journey protection or active dependency blocks this path.')
        if executor.is_protected(self.conn, str(path)) or executor.get_active_dependents(self.conn,str(path)):
            raise PermissionError('This path is protected or has an active registered dependency.')

    def validate_operation(self, batch, operation, *, source):
        scope = Path(batch['scope'])
        destination = Path(operation['destination'])
        if operation['kind'] in ('rename', 'move'):
            require_preserved_filename(operation['source'], destination)
        if not destination.is_relative_to(scope) or destination == scope:
            raise ValueError('The destination is outside the reviewed scope.')
        self.guard(batch['id'], destination)
        parent = safe_metadata(destination.parent, read_guard=lambda p: self.guard(batch['id'], p))
        expected = operation['parent']
        if (parent.st_dev, parent.st_ino) != tuple(expected):
            raise ValueError('The destination parent changed since review.')
        if os.path.lexists(destination):
            raise ValueError('The destination is occupied. Review a different name.')
        if operation['kind'] in ('rename', 'move', 'undo') and source:
            path = Path(operation['source'])
            if not path.is_relative_to(scope) or path.suffix != destination.suffix:
                raise ValueError('A source must remain in scope and keep its original extension.')
            self.guard(batch['id'], path)
            if executor.get_active_dependents(self.conn, str(path)):
                raise ValueError('An active registered dependency blocks this operation.')
            current = file_identity(path, read_guard=lambda p: self.guard(batch['id'], p))
            if current != operation['identity'] or current['device'] != parent.st_dev:
                raise ValueError('Source identity changed or this move crosses a volume.')

    def prepare(self, job_id, operations):
        app = self.workbench
        job = app.job(job_id)
        app.policy.refresh()
        if not app._validate_scope(job, job['root']) or not app.retains:
            raise PermissionError('A retained scope with proposal permission is required for Guided Patrol.')
        if not isinstance(operations, list) or not 1 <= len(operations) <= MAX_BATCH:
            raise ValueError('Review a batch containing 1–20 operations.')
        check_operation_magnitude(len(operations), app.summary(job_id)['files'], operation_label='Guided Patrol')
        batch_id, scope = uuid4().hex, job['root']
        prepared = []
        for request in operations:
            kind = request['kind']
            if kind not in ('rename', 'move', 'mkdir'):
                raise ValueError('Guided Patrol supports creating a folder, renaming a file, or moving a file within one scope.')
            target = Path(request['destination'])
            component(target.name)
            if not target.is_absolute() or '..' in target.parts or not target.is_relative_to(scope):
                raise ValueError('Choose an exact destination inside this scope.')
            operation = {'kind': kind, 'destination': str(target), 'reason': str(request.get('reason','Improve findability'))[:500]}
            app.policy.check(target)
            parent = safe_metadata(target.parent, read_guard=app.policy.check)
            operation['parent'] = [parent.st_dev, parent.st_ino]
            if kind != 'mkdir':
                row = app.conn.execute("SELECT * FROM files WHERE job=? AND id=? AND epoch=? AND status='analyzed' AND scope=?",
                                       (job_id, request['asset'], job['epoch'], scope)).fetchone()
                if row is None:
                    raise ValueError('Choose a current analyzed image in the original scope.')
                path = Path(row['path'])
                require_preserved_filename(path, target)
                app.policy.check_image(path, retain=True)
                operation['source'] = str(path)
                operation['identity'] = file_identity(path, read_guard=app.policy.check)
                if not operation['identity'] or operation['identity']['sha256'] != row['digest']:
                    raise ValueError('The image changed. Refresh before reviewing a physical operation.')
                if kind == 'rename' and target.parent != path.parent:
                    raise ValueError('A rename keeps its original parent folder. Choose move for another folder.')
            prepared.append(operation)
        sources = [operation['source'] for operation in prepared if 'source' in operation]
        targets = [operation['destination'].casefold() for operation in prepared]
        if len(set(sources)) != len(sources) or len(set(targets)) != len(targets):
            raise ValueError('Each source and destination can occur once in a batch.')
        with self.conn:
            proposal = self.conn.execute("INSERT INTO proposals(description,status) VALUES(?,'pending')", ('Guided Patrol '+batch_id,)).lastrowid
            for position, operation in enumerate(prepared):
                item = None
                if 'source' in operation:
                    item = self.conn.execute("INSERT INTO proposal_items(proposal_id,canonical_path,dest_path,requested_mode) VALUES(?,?,?,'move')",
                                             (proposal, operation['source'], operation['destination'])).lastrowid
                    operation['item'] = item
                self.conn.execute('INSERT INTO guided_operations(batch,position,item) VALUES(?,?,?)', (batch_id,position,item))
            payload = {'operations': prepared, 'scope': scope, 'job': job_id}
            binding = sha256(encoded(payload).encode()).hexdigest()
            self.conn.execute('INSERT INTO guided_batches(id,job,scope,payload,binding,status,proposal) VALUES(?,?,?,?,?,\'review_required\',?)',
                              (batch_id,job_id,scope,encoded(payload),binding,proposal))
        try:
            batch = self.row(batch_id)
            for operation in prepared:
                self.validate_operation(batch, operation, source=True)
        except (OSError,ValueError) as error:
            with self.conn:
                self.conn.execute("UPDATE guided_batches SET status='blocked',reason=? WHERE id=?", (str(error),batch_id))
            raise
        return self.view(batch_id)

    def view(self, batch_id):
        batch = self.row(batch_id)
        self.workbench.policy.refresh()
        self.workbench._validate_scope(self.workbench.job(batch['job']), batch['scope'])
        return {key: batch[key] for key in ('id','job','scope','binding','status','reason','created')} | {
            'operations': json.loads(batch['payload'])['operations'],
            'progress': [dict(row) for row in self.conn.execute('SELECT position,receipt,status,reason FROM guided_operations WHERE batch=? ORDER BY position',(batch_id,))],
            'approval': json.loads(batch['approval']) if batch['approval'] else None}

    def prepare_undo(self, job_id, receipt):
        self.workbench._visible(self.workbench.job(job_id))
        known=self.conn.execute('SELECT b.scope FROM guided_operations o JOIN guided_batches b ON b.id=o.batch WHERE b.job=? AND o.receipt=?',
                                (job_id,receipt)).fetchone()
        row=self.conn.execute("SELECT * FROM action_log WHERE id=? AND action_type='file_move' AND status='applied'",(receipt,)).fetchone()
        if known is None or row is None:
            raise ValueError('Choose a verified file operation from this Destination.')
        previous,current=json.loads(row['previous_state']),json.loads(row['new_state'])
        parent=safe_metadata(Path(previous['path']).parent,read_guard=self.workbench.policy.check)
        operation={'kind':'undo','receipt':receipt,'source':current['path'],'destination':previous['path'],
                   'original_receipt_binding':receipt_binding(row),
                   'identity':current['identity'],'parent':[parent.st_dev,parent.st_ino],
                   'reason':'Reverse this exact verified operation while preserving any new occupants.'}
        payload={'job':job_id,'scope':known['scope'],'operations':[operation]}
        batch_id=uuid4().hex
        with self.conn:
            self.conn.execute("INSERT INTO guided_batches(id,job,scope,payload,binding,status) VALUES(?,?,?,?,?,'review_required')",
                (batch_id,job_id,known['scope'],encoded(payload),sha256(encoded(payload).encode()).hexdigest()))
            self.conn.execute('INSERT INTO guided_operations(batch,position) VALUES(?,0)',(batch_id,))
        self.validate_operation(self.row(batch_id),operation,source=True)
        return self.view(batch_id)

    def begin_approval(self, batch_id):
        batch = self.row(batch_id)
        if batch['status'] not in ('review_required','blocked','partially_completed'):
            raise ValueError('This batch is already being approved or has finished.')
        for operation in self.pending_operations(batch_id):
            self.validate_operation(batch, operation, source=True)
        with self.conn:
            self.conn.execute("UPDATE guided_batches SET status='authorizing',approval=NULL,proof=NULL,reason='' WHERE id=?",(batch_id,))
        return batch['binding'], self.description(batch_id)

    def description(self, batch_id):
        batch = self.row(batch_id)
        lines = ['Review this exact Guided Patrol batch.', 'Scope: '+batch['scope'], 'Batch: '+batch['binding'], '']
        for operation in self.pending_operations(batch_id):
            lines += [operation['kind'].upper(), operation.get('source','New folder'), '→ '+operation['destination'], operation['reason'], '']
        lines += ['Approving confirms the listed changes and your assessment that these exact source paths have no unresolved external use or references within your responsibility.',
                  'Known protections and registered dependencies still block execution. Approve using your current Windows account?']
        return '\n'.join(lines)

    def pending_operations(self,batch_id):
        operations=json.loads(self.row(batch_id)['payload'])['operations']
        positions={row[0] for row in self.conn.execute("SELECT position FROM guided_operations WHERE batch=? AND status='pending'",(batch_id,))}
        if not positions:
            raise ValueError('This batch has no pending actions. Review a new batch for changed or failed operations.')
        return [operation for position,operation in enumerate(operations) if position in positions]

    def accept(self, batch_id, consent):
        batch = self.row(batch_id)
        if (batch['status'] != 'authorizing' or consent.binding != batch['binding'] or time.time()-consent.verified_at > 60
                or sha256(batch['payload'].encode()).hexdigest()!=batch['binding']):
            raise PermissionError('The batch or account approval changed. Review it again.')
        for operation in self.pending_operations(batch_id):
            self.validate_operation(batch, operation, source=True)
        approval = asdict(consent) | {'expires_at': consent.verified_at + EXPIRY,
                                     'dependency_disposition': 'Account-approved exact-source assessment'}
        with self.conn:
            self.conn.execute("UPDATE proposals SET status='approved',resolved_at=datetime('now') WHERE id=?",(batch['proposal'],))
            if batch['proposal'] is not None:
                approval['proposal_binding']=approval_binding(self.conn.execute('SELECT * FROM proposals WHERE id=?',(batch['proposal'],)).fetchone())
            proof = hmac.new(self.key, (batch['payload']+encoded(approval)).encode(), 'sha256').hexdigest()
            self.conn.execute("UPDATE guided_batches SET status='approved',approval=?,proof=? WHERE id=?",(encoded(approval),proof,batch_id))
        return self.view(batch_id)

    def authorized(self, batch_id):
        batch = self.row(batch_id)
        if batch['status'] not in ('approved','working') or not batch['approval']:
            raise MoveEvidenceDenied('The exact batch has no active account approval.')
        approval = json.loads(batch['approval'])
        proof = hmac.new(self.key,(batch['payload']+encoded(approval)).encode(),'sha256').hexdigest()
        if not hmac.compare_digest(proof,batch['proof']) or not approval['verified_at'] <= time.time() < approval['expires_at']:
            raise MoveEvidenceDenied('Approval integrity or expiry requires a new review.')
        if sha256(batch['payload'].encode()).hexdigest() != batch['binding']:
            raise MoveEvidenceDenied('The reviewed batch changed.')
        if batch['proposal'] is not None:
            proposal=self.conn.execute('SELECT * FROM proposals WHERE id=?',(batch['proposal'],)).fetchone()
            if not proposal or proposal['status']!='approved' or approval_binding(proposal)!=approval['proposal_binding']:
                raise MoveEvidenceDenied('The approved operation proposal changed.')
        for operation in json.loads(batch['payload'])['operations']:
            if operation['kind']=='undo':
                receipt=self.conn.execute('SELECT * FROM action_log WHERE id=?',(operation['receipt'],)).fetchone()
                if not receipt or receipt_binding(receipt)!=operation['original_receipt_binding']:
                    raise MoveEvidenceDenied('The original operation receipt changed after reversal review.')
        self.guard(batch_id, Path(batch['scope']))
        return batch,json.loads(batch['payload']),approval

    def step(self, batch_id):
        batch,payload,_ = self.authorized(batch_id)
        pending = self.conn.execute("SELECT * FROM guided_operations WHERE batch=? AND status='pending' ORDER BY position LIMIT 1",(batch_id,)).fetchone()
        if pending is None:
            return self.view(batch_id)
        operation = payload['operations'][pending['position']]
        previous_receipt=self.conn.execute('SELECT coalesce(max(id),0) FROM action_log').fetchone()[0]
        receipt, status, reason = None, 'failed', ''
        try:
            self.validate_operation(batch, operation, source=True)
            with self.conn:
                self.conn.execute("UPDATE guided_batches SET status='working' WHERE id=?",(batch_id,))
            if operation['kind'] == 'undo':
                result=executor.undo_apply(self.conn,operation['receipt'],read_guard=lambda p:self.guard(batch_id,p),
                    authorize=lambda:self.authorized(batch_id))
                if result['status']!='reversed':
                    raise ValueError(result.get('evidence',{}).get('reason',result['status']))
                receipt,status=result['reversal_op_id'],'verified'
            elif operation['kind'] == 'mkdir':
                result = executor.execute_folder(self.conn, operation['destination'],
                    read_guard=lambda p: self.guard(batch_id,p), authorize=lambda: self.authorized(batch_id))
                receipt, status = result['op_id'], 'verified'
            else:
                known = self.workbench.conn.execute('SELECT path FROM files WHERE job=? AND epoch=? AND scope=?',
                    (batch['job'],self.workbench.job(batch['job'])['epoch'],batch['scope'])).fetchall()
                for row in known:
                    self.conn.execute("INSERT OR IGNORE INTO files(canonical_path,status) VALUES(?,'present')",(row['path'],))
                self.conn.commit()
                verifier = GuidedVerifier(self,batch_id)
                result = executor.execute_apply(self.conn, {'to_apply':[{'item_id':operation['item'],'action':'move'}]},verbose=False,move_verifier=verifier)
                if result.get('applied'):
                    receipt, status = result['applied'][0]['op_id'], 'verified'
                else:
                    raise ValueError(result.get('reason') or str(result.get('failed', 'Execution was blocked.')))
        except (OSError,ValueError,PermissionError) as error:
            reason = str(error)
            if receipt is None:
                saved=self.conn.execute('SELECT id FROM action_log WHERE id>? ORDER BY id DESC LIMIT 1',(previous_receipt,)).fetchone()
                receipt=saved['id'] if saved else None
        with self.conn:
            self.conn.execute('UPDATE guided_operations SET status=?,receipt=?,reason=? WHERE batch=? AND position=?',
                              (status,receipt,reason,batch_id,pending['position']))
            left = self.conn.execute("SELECT count(*) FROM guided_operations WHERE batch=? AND status='pending'",(batch_id,)).fetchone()[0]
            failures = self.conn.execute("SELECT count(*) FROM guided_operations WHERE batch=? AND status='failed'",(batch_id,)).fetchone()[0]
            verified=self.conn.execute("SELECT count(*) FROM guided_operations WHERE batch=? AND status='verified'",(batch_id,)).fetchone()[0]
            final = 'completed'
            if left:
                final = 'approved'
            elif failures:
                final = 'partially_completed' if verified else ('failed' if receipt else 'blocked')
            self.conn.execute('UPDATE guided_batches SET status=?,reason=? WHERE id=?',(final,reason,batch_id))
        if status=='verified' and 'source' in operation:
            with self.workbench.conn:
                self.workbench.conn.execute('INSERT INTO asset_transitions(job,scope,digest,from_path,to_path,receipt) VALUES(?,?,?,?,?,?)',
                    (batch['job'],batch['scope'],operation['identity']['sha256'],operation['source'],operation['destination'],receipt))
        if not left and self.conn.execute("SELECT 1 FROM guided_operations WHERE batch=? AND status='verified'",(batch_id,)).fetchone():
            self.workbench.refresh(batch['job'])
            tables={row[0] for row in self.workbench.conn.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
            if 'patrol_tasks' in tables:
                with self.workbench.conn:
                    self.workbench.conn.execute("UPDATE patrol_tasks SET status='pending',cursor=0 WHERE destination IN (SELECT id FROM destinations WHERE job=?)",(batch['job'],))
                    for table in ('patrol_assets','virtual_memberships'):
                        self.workbench.conn.execute(f'DELETE FROM {table} WHERE destination IN (SELECT id FROM destinations WHERE job=?)',(batch['job'],))
        return self.view(batch_id)

    def history(self, job_id):
        self.workbench._visible(self.workbench.job(job_id))
        return [dict(row) for row in self.conn.execute('SELECT id,action_type,target_path,status,performed_at,new_state FROM action_log ORDER BY id DESC LIMIT 100')
                if any(row['id']==event['receipt'] for event in self.conn.execute('SELECT receipt FROM guided_operations o JOIN guided_batches b ON o.batch=b.id WHERE b.job=?',(job_id,)))]
