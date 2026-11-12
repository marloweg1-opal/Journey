"""Exact-file housekeeping through existing Guided approval, with bounded recovery."""

from collections import defaultdict
from hashlib import sha256
from io import BytesIO
import ctypes
import gzip
import json
import os
from pathlib import Path
import re
import stat
from time import monotonic, time
from uuid import uuid4

from core import journal
from core.circuit_breaker import OperationTooLarge, check_operation_magnitude
from core.file_paths import safe_metadata, signature
from core.patrol_state import read_state
from core.recovery_inspection import file_identity
from journey_navigator.guided import encoded, receipt_binding
from journey_navigator.stewardship import scan_references
from journey_vision.observe import IMAGE_FORMATS, decode_image, image_bytes
from journey_vision.steward import pixel_distance

MAX_FILE = 256_000_000
RECOVERY_FILE = 16 * 1024 * 1024
RECOVERY_QUOTA = 256 * 1024 * 1024
RETENTION = 7 * 86400
SCHEMA = """
CREATE TABLE IF NOT EXISTS duplicate_inventory(job TEXT,asset INTEGER,epoch INTEGER,record TEXT,PRIMARY KEY(job,asset));
CREATE TABLE IF NOT EXISTS duplicate_audits(job TEXT PRIMARY KEY,id TEXT,record TEXT);
CREATE TABLE IF NOT EXISTS duplicate_recovery(id TEXT PRIMARY KEY,batch TEXT,receipt INTEGER,source TEXT,backup TEXT,
 digest TEXT,size INTEGER,mode INTEGER,mtime INTEGER,expires REAL,state TEXT);
"""
COPY = re.compile(r'(?:\s*\([1-9][0-9]*\)|[ _-]+copy(?:[ _-]*[0-9]+)?)$', re.I)


def is_copy(source, keeper):
    a,b=Path(source),Path(keeper)
    return a.parent==b.parent and a.suffix.casefold()==b.suffix.casefold() and COPY.sub('',a.stem).casefold()==b.stem.casefold() and a.stem!=b.stem


def move_no_replace(source, target):
    if os.name=='nt':
        os.rename(source,target)  # Windows refuses an occupied destination.
    elif os.name=='posix':
        libc=ctypes.CDLL(None,use_errno=True)
        function=getattr(libc,'renameat2',None)
        if function is None:
            raise PermissionError('No verified no-replace rename is available on this platform.')
        function.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint]
        if function(-100,os.fsencode(source),-100,os.fsencode(target),1):
            error=ctypes.get_errno();raise OSError(error,os.strerror(error),str(target))
    else:
        raise PermissionError('This platform has no verified cleanup rename primitive.')


class DuplicatePatrol:
    def __init__(self, patrol):
        self.patrol,self.app,self.conn=patrol,patrol.app,patrol.app.conn
        self.conn.executescript(SCHEMA)
        self.grants={};self.watches={};self.watch_errors={};self.due=0
        self.audit_options={};self.pending_audits=set();self.audit_errors={};self.auto_count=defaultdict(int)
        self.recovery=self.app.data_dir/'duplicate-recovery'
        self.patrol.guided.duplicate_handler=self
        with self.conn:self.conn.execute("UPDATE duplicate_recovery SET state='manual_recovery_required' WHERE state='prepared'")

    def scope(self, job):
        row=self.app.job(job)
        if not self.app.retains:raise PermissionError('Keep a local checkpoint before auditing duplicates.')
        self.app._validate_scope(row,row['root'])
        self.app.policy.refresh()
        return row

    def grant_preview(self, job, automatic=False):
        row=self.scope(job)
        if not self.app._validate_scope(row,row['root']):raise PermissionError('Allow proposals for this scope before enabling execution.')
        if type(automatic) is not bool:raise ValueError('Choose whether the bounded automatic rule is enabled.')
        proposal={'id':uuid4().hex,'job':job,'scope':row['root'],'automatic':automatic,'duration':3600,
                  'recovery_days':7,'max_per_cycle':20,'max_per_session':100,'max_file_bytes':RECOVERY_FILE}
        self.pending_grant=proposal
        binding=sha256(encoded(proposal).encode()).hexdigest()
        text=('Enable recoverable duplicate removal ONLY in '+row['root']+' for this Navigator session (at most one hour). '
              'This deliberately lifts the copy-only/no-deletion trial restriction for this scope. '
              'Exact reviewed batches still require approval. Every removed file receives a verified temporary recovery checkpoint, '
              'retained for seven days and then expired when Navigator next runs. No permanent duplicate archive is created. '
              'Known protections, approved paths and dependencies remain binding. '
              'You confirm responsibility for unresolved external references before approving a cleanup batch. ')
        if automatic:
            text+=('Also authorize automatic removal ONLY of same-folder, same-extension copy-suffix exact duplicates, '
                   'without accepted path decisions or scoped/registered references: at most 20 per cycle and 100 per session. '
                   'Other variations require separate review. This is not a general deletion permission.')
        return binding,text

    def activate(self, binding, consent):
        proposal=getattr(self,'pending_grant',None)
        if not proposal or consent.binding!=binding or sha256(encoded(proposal).encode()).hexdigest()!=binding or time()-consent.verified_at>60:
            raise PermissionError('The scope permission review changed or expired.')
        self.scope(proposal['job'])
        self.grants[proposal['job']]=proposal|{'binding':binding,'account':consent.account,'method':consent.method,
            'verified_at':consent.verified_at,'expires_at':consent.verified_at+proposal['duration']}
        self.pending_grant=None
        return self.permission(proposal['job'])

    def permission(self, job):
        grant=self.grants.get(job)
        return {'enabled':bool(grant and time()<grant['expires_at']), 'automatic':bool(grant and grant['automatic'] and time()<grant['expires_at']),
                'session_only':True,'recovery_days':7,'expires_at':grant['expires_at'] if grant else None}

    def revoke(self, job):
        self.grants.pop(job,None);self.watches.pop(job,None)
        return self.permission(job)

    def begin(self, job, read_references=False):
        row=self.scope(job)
        if type(read_references) is not bool:raise ValueError('Choose reference-reading permission explicitly.')
        self.audit_options[job]=read_references
        with self.conn:self.conn.execute('DELETE FROM duplicate_audits WHERE job=?',(job,))
        return self.status(job)

    def queue(self, job, read_references=False):
        self.scope(job);self.app.refresh(job)
        self.begin(job,read_references)
        self.pending_audits.add(job);self.audit_errors.pop(job,None)
        self.patrol.wake.set()
        return self.status(job)

    def advance(self):
        if not self.pending_audits or read_state(self.conn)['paused']:return False
        job=next(iter(self.pending_audits))
        try:
            if self.audit_step(job):self.pending_audits.discard(job)
        except (OSError,ValueError) as error:
            self.pending_audits.discard(job);self.audit_errors[job]=str(error)
        return bool(self.pending_audits)

    def audit_step(self, job):
        row=self.scope(job)
        if self.app.summary(job)['pending_folders']:
            self.app.step(job,analyze=False)
            return False
        files=self.conn.execute("""SELECT f.* FROM files f LEFT JOIN duplicate_inventory d ON d.job=f.job AND d.asset=f.id
            WHERE f.job=? AND f.epoch=? AND f.scope=? AND (d.asset IS NULL OR d.epoch<>f.epoch) ORDER BY f.id LIMIT 64""",
            (job,row['epoch'],row['root'])).fetchall()
        new_hashes=0
        for file in files:
            path=Path(file['path']);record={'id':file['id'],'path':str(path),'name':path.name,'size':file['size'],'error':None}
            prior=self.conn.execute('SELECT record FROM duplicate_inventory WHERE job=? AND asset=?',(job,file['id'])).fetchone()
            try:
                observed=safe_metadata(path,read_guard=self.app.policy.check)
                prior=json.loads(prior[0]) if prior else None
                key=[*signature(observed),observed.st_size]
                if prior and prior.get('signature')==key and prior.get('identity'):
                    record=prior|{'reused_hash':True}
                else:
                    if new_hashes>=4:break
                    new_hashes+=1
                    identity=file_identity(path,max_bytes=MAX_FILE,read_guard=self.app.policy.check)
                    if not identity:raise ValueError('File changed, is linked, unreadable, or exceeds the 256 MB hash budget.')
                    record.update(identity=identity,signature=key,reused_hash=False)
                    if path.suffix.casefold() in IMAGE_FORMATS:
                        self.app.policy.check_image(path,retain=True)
                        self.app._analyze(row,file,{row['root']},read_text=False)
                        refreshed=self.conn.execute('SELECT digest,status FROM files WHERE id=?',(file['id'],)).fetchone()
                        if refreshed['status']=='analyzed':
                            features=self.conn.execute('SELECT features FROM observations WHERE job=? AND scope=? AND digest=?',
                                (job,row['root'],refreshed['digest'])).fetchone()
                            record['features']=json.loads(features[0])
                            image=decode_image(image_bytes(path),IMAGE_FORMATS[path.suffix.casefold()])
                            values=list(image.convert('L').resize((9,8)).getdata())
                            record['dhash']=sum((values[y*9+x]>values[y*9+x+1]) << (y*8+x) for y in range(8) for x in range(8))
                if record.get('features') and file['status']=='pending':
                    cached=self.conn.execute('SELECT series FROM observations WHERE job=? AND scope=? AND digest=?',
                        (job,row['root'],record['identity']['sha256'])).fetchone()
                    if cached:self.conn.execute("UPDATE files SET status='analyzed',digest=?,series=?,reused=1 WHERE id=?",
                        (record['identity']['sha256'],cached[0],file['id']))
                self.conn.execute('INSERT OR REPLACE INTO duplicate_inventory VALUES(?,?,?,?)',(job,file['id'],row['epoch'],json.dumps(record)))
            except (OSError,ValueError) as error:
                record['error']=str(error)
                self.conn.execute('INSERT OR REPLACE INTO duplicate_inventory VALUES(?,?,?,?)',(job,file['id'],row['epoch'],json.dumps(record)))
        self.conn.commit()
        if files:return False
        self._publish(job)
        return True

    def records(self, job):
        row=self.scope(job)
        return [json.loads(r[0]) for r in self.conn.execute('SELECT record FROM duplicate_inventory WHERE job=? AND epoch=?',(job,row['epoch']))]

    def accepted_paths(self, job):
        paths=set()
        for row in self.conn.execute('SELECT event FROM reviews WHERE job=?',(job,)):
            event=json.loads(row[0])
            if event['action'] in ('confirm','purpose'):paths.add(event['source_path'])
        audit=self.app.project_audit.document(job)
        if audit:
            examples={(r['filename'].casefold(),r.get('sha256')) for r in audit['examples']}
            paths.update(r['path'] for r in self.records(job) if (r['name'].casefold(),r.get('identity',{}).get('sha256')) in examples)
        return paths

    def blockers(self, path, accepted):
        if Path(path).name.startswith('.journey-'):return 'A managed staging or recovery file requires explicit recovery review.'
        if str(path) in accepted:return 'An accepted path or attributed exemplar is authoritative.'
        try:self.patrol.guided.require_unprotected(Path(path))
        except (OSError,ValueError) as error:return str(error)
        return ''

    def _publish(self, job):
        row=self.scope(job);records=self.records(job);accepted=self.accepted_paths(job)
        buckets=defaultdict(list)
        for item in records:
            if item.get('identity'):buckets[item['identity']['sha256']].append(item)
        repeated=[items for items in buckets.values() if len(items)>1]
        candidates=[i['path'] for group in repeated for i in group]
        reading=self.audit_options.get(job,False)
        refs=scan_references(self.app,row['root'],candidates) if reading and candidates else {
            'state':'NOT_REQUESTED','gaps':0,'references':[],'global_clearance':False}
        referenced={r['target'] for r in refs['references']}
        groups=[]
        for items in repeated:
            # Protections and accepted paths outrank lexical copy hints.
            items=sorted(items,key=lambda x:(not(bool(self.blockers(x['path'],accepted)) or x['path'] in referenced),
                bool(COPY.search(Path(x['path']).stem)),len(x['path']),x['path']))
            keep=items[0];remove=[];held=[]
            for item in items[1:]:
                reason=self.blockers(item['path'],accepted)
                if item['path'] in referenced:reason='Scoped documentation or configuration references this path.'
                if item['identity']['inode']==keep['identity']['inode'] and item['identity']['device']==keep['identity']['device']:
                    reason='Hard-link aliases do not represent separately reclaimable file content.'
                if reason:held.append(item|{'hold':reason})
                else:remove.append(item|{'automatic_candidate':is_copy(item['path'],keep['path'])})
            groups.append({'digest':keep['identity']['sha256'],'keep':keep,'remove':remove,'held':held,
                'reason':'Exact SHA-256 equality. Retain accepted/protected/referenced paths first; remaining role equivalence requires approval.'})
        images=[i for i in records if i.get('features') and i.get('dhash') is not None]
        near=[];comparisons=0
        for index,a in enumerate(images[:1000]):
            for b in images[index+1:1000]:
                if comparisons>=20000:break
                if a['identity']['sha256']==b['identity']['sha256']:continue
                comparisons+=1
                if (a['dhash']^b['dhash']).bit_count()>10:continue
                distance=pixel_distance(a['features'],b['features'])
                if distance>.13:continue
                quality=lambda v:(v['path'] in accepted,v['features']['width']*v['features']['height'],
                    Path(v['path']).suffix.casefold() in ('.png','.tif','.tiff'),v['size'])
                pair=sorted([a,b],key=quality,reverse=True)
                near.append({'preferred':pair[0],'variation':pair[1],'pixel_distance':round(distance,5),
                    'state':'variation_review','reason':'Different bytes: possible resize, compressed export or alternate design. Preserve both until reviewed; no automatic deletion.'})
            if comparisons>=20000:break
        def compact(item):
            return {key:value for key,value in item.items() if key not in ('features','dhash','signature')} | (
                {'dimensions':[item['features']['width'],item['features']['height']]} if item.get('features') else {})
        for group in groups:
            group['keep']=compact(group['keep'])
            for kind in ('remove','held'):group[kind]=list(map(compact,group[kind]))
        for pair in near:
            for kind in ('preferred','variation'):pair[kind]=compact(pair[kind])
        removed={i['id'] for g in groups for i in g['remove']}
        broad=defaultdict(list)
        offset=0
        while True:
            page=self.app.images(job,offset,thumbnails=False)
            for image in page['items']:
                if image['id'] not in removed:
                    broad[image['identity']['label'] or image['purpose']['label'] or 'Unassigned distinct assets'].append(image['id'])
            if not page['more']:break
            offset+=24
        result={'id':uuid4().hex,'job':job,'scope':row['root'],'epoch':row['epoch'],'exact_groups':groups,
            'near_duplicates':near[:100],'near_comparisons':comparisons,'near_coverage_limited':len(images)>1000 or comparisons>=20000,
            'hash_errors':[i for i in records if i.get('error')],'hashes_reused':sum(bool(i.get('reused_hash')) for i in records),
            'files_audited':len(records),'references':refs,'read_references':reading,
            'proposed_removals':sum(len(g['remove']) for g in groups),'projected_recoverable_bytes':sum(i['size'] for g in groups for i in g['remove']),
            'immediate_space_guaranteed':0,'recovery_policy':{'days':7,'quota_bytes':RECOVERY_QUOTA,'per_file_bytes':RECOVERY_FILE,
              'note':'Temporary recoverability consumes storage until checkpoints expire. Projected bytes are not immediate free-space measurements.'},
            'broad_groups':[{'label':k,'assets':v,'physical_changes':False} for k,v in broad.items()],
            'canonical_changes':False,'physical_changes':False,'created':time()}
        with self.conn:self.conn.execute('INSERT OR REPLACE INTO duplicate_audits VALUES(?,?,?)',(job,result['id'],json.dumps(result)))
        return result

    def status(self, job):
        row=self.scope(job)
        saved=self.conn.execute('SELECT record FROM duplicate_audits WHERE job=?',(job,)).fetchone()
        result=json.loads(saved[0]) if saved else None
        progress=self.conn.execute('SELECT count(*) FROM duplicate_inventory WHERE job=? AND epoch=?',(job,row['epoch'])).fetchone()[0]
        return {'audit':result,'audited':progress,'current':bool(result and result['epoch']==row['epoch']),
                'permission':self.permission(job),'monitor':job in self.watches,'monitor_error':self.watch_errors.get(job,''),'running':job in self.pending_audits,
                'error':self.audit_errors.get(job,''),'recovery':self.recovery_status(job)}

    def prepare(self, job, audit, assets):
        row=self.scope(job);state=self.status(job)
        if not self.permission(job)['enabled']:raise PermissionError('Duplicate removal is locked. Deliberately establish scoped execution permission first.')
        result=state['audit']
        if not result or not state['current'] or result['id']!=audit:raise ValueError('Review a current duplicate audit first.')
        if not isinstance(assets,list) or not 1<=len(assets)<=100 or len(set(assets))!=len(assets):raise ValueError('Review 1–100 distinct redundant copies.')
        if result['references']['state']!='CHECKED_WITHIN_SCOPE':raise PermissionError('A complete scoped reference check is required before cleanup.')
        check_operation_magnitude(len(assets),result['files_audited'],operation_label='Duplicate cleanup')
        operations=[];accepted=self.accepted_paths(job)
        for group in result['exact_groups']:
            for item in group['remove']:
                if item['id'] not in assets:continue
                if item['size']>RECOVERY_FILE:raise ValueError('A selected file exceeds the 16 MiB recoverable cleanup limit.')
                operations.append({'kind':'dedupe_delete','source':item['path'],'destination':group['keep']['path'],
                    'identity':item['identity'],'keeper_identity':group['keep']['identity'],'asset':item['id'],
                    'audit':audit,'recovery_days':7,'reason':'Confirmed redundant exact copy; retain '+group['keep']['path']})
        if len(operations)!=len(assets):raise ValueError('Selection includes a held file or non-exact variation.')
        if sum(o['identity']['size'] for o in operations)>RECOVERY_QUOTA:raise ValueError('The temporary recovery quota would be exceeded.')
        if {o['source'] for o in operations}&{o['destination'] for o in operations}:raise ValueError('A retained copy cannot also be removed.')
        return self.patrol.guided.prepare_duplicate(job,operations)

    def validate(self, batch, operation, *, source=True):
        job=batch['job'];row=self.scope(job)
        if not self.app._validate_scope(row,row['root']):raise PermissionError('Proposal permission was revoked.')
        if not self.permission(job)['enabled']:raise PermissionError('Scoped duplicate execution permission is inactive.')
        if operation['kind']=='dedupe_restore':
            self._recovery_record(operation['recovery'])
            path=Path(operation['destination'])
            self.patrol.guided.guard(batch['id'],path)
            safe_metadata(path.parent,read_guard=self.app.policy.check)
            if os.path.lexists(path):raise ValueError('Restore destination is occupied. No overwrite is permitted.')
            return
        path,keeper=Path(operation['source']),Path(operation['destination'])
        if path==keeper or not path.is_relative_to(row['root']) or not keeper.is_relative_to(row['root']):raise PermissionError('Cleanup paths must stay in their approved original scope.')
        self.patrol.guided.guard(batch['id'],path)
        if self.blockers(path,self.accepted_paths(job)):raise PermissionError('A protected or accepted path cannot be removed.')
        current=file_identity(path,read_guard=self.app.policy.check)
        retained=file_identity(keeper,read_guard=self.app.policy.check)
        if current!=operation['identity'] or retained!=operation['keeper_identity'] or current['sha256']!=retained['sha256']:
            raise ValueError('Source or retained-copy identity changed. Review cleanup again.')
        refs=scan_references(self.app,row['root'],[str(path)])
        if refs['state']!='CHECKED_WITHIN_SCOPE' or refs['references']:raise PermissionError('A dependency/reference or incomplete reference scan holds this file.')
        if batch['approval']:
            approval=json.loads(batch['approval'])
            if approval.get('rule_grant'):self.verify_rule(batch['id'],approval['rule_grant'])

    def _recovery_record(self, identifier):
        record=self.conn.execute('SELECT * FROM duplicate_recovery WHERE id=?',(identifier,)).fetchone()
        if not record or record['state']!='removed' or time()>=record['expires']:raise ValueError('The recovery checkpoint is unavailable or expired.')
        backup=Path(record['backup'])
        if backup.parent!=self.recovery:raise PermissionError('Recovery path is outside managed storage.')
        safe_metadata(backup)
        with gzip.open(backup,'rb') as stream:data=stream.read(RECOVERY_FILE+1)
        if len(data)!=record['size'] or sha256(data).hexdigest()!=record['digest']:raise ValueError('The recovery checkpoint changed.')
        return record,data

    def execute(self, batch, operation):
        guided=self.patrol.guided
        self.validate(batch,operation)
        if operation['kind']=='dedupe_restore':
            record,data=self._recovery_record(operation['recovery']);target=Path(operation['destination'])
            temporary=target.parent/('.journey-restore-'+uuid4().hex)
            preview=journal.preview_operation(guided.conn,'duplicate_restore',3,str(target),{'recovery':record['id']})
            receipt=journal.begin_transaction(guided.conn,preview,{'recovery':record['id'],'path':str(target)})
            with temporary.open('xb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
            try:
                guided.authorized(batch['id']);self.validate(batch,operation)
                move_no_replace(temporary,target)
                os.chmod(target,record['mode']);os.utime(target,ns=(record['mtime'],record['mtime']))
            finally:temporary.unlink(missing_ok=True)
            with self.conn:self.conn.execute("UPDATE duplicate_recovery SET state='restored' WHERE id=?",(record['id'],))
            journal.complete_operation(guided.conn,receipt,{'path':str(target),'recovery':record['id']},True,read_guard=self.app.policy.check)
            with guided.conn:guided.conn.execute("UPDATE action_log SET status='reversed' WHERE id=?",(record['receipt'],))
            return receipt
        path=Path(operation['source']);identity=operation['identity']
        self.recovery.mkdir(exist_ok=True);safe_metadata(self.recovery)
        usage=sum(p.stat().st_size for p in self.recovery.glob('*.gz'))
        if usage+identity['size']>RECOVERY_QUOTA:raise ValueError('Temporary recovery storage is full; cleanup is held.')
        identifier=uuid4().hex;backup=self.recovery/(identifier+'.gz');stage=path.parent/('.journey-remove-'+identifier)
        info=safe_metadata(path,read_guard=self.app.policy.check)
        data=path.read_bytes()
        if len(data)!=identity['size'] or sha256(data).hexdigest()!=identity['sha256']:raise ValueError('The redundant source changed.')
        with backup.open('xb') as raw:
            os.chmod(backup,0o600)
            with gzip.GzipFile(fileobj=raw,mode='wb') as stream:stream.write(data)
            raw.flush();os.fsync(raw.fileno())
        with gzip.open(backup,'rb') as stream:
            if sha256(stream.read(RECOVERY_FILE+1)).hexdigest()!=identity['sha256']:raise ValueError('Recovery verification failed.')
        preview=journal.preview_operation(guided.conn,'duplicate_remove',3,str(path),{'retained':operation['destination'],'recovery_days':7})
        receipt=journal.begin_transaction(guided.conn,preview,{'path':str(path),'identity':identity,'keeper':operation['destination'],
            'recovery':identifier,'staging_path':str(stage),'backup':str(backup)})
        with self.conn:self.conn.execute('INSERT INTO duplicate_recovery VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            (identifier,batch['id'],receipt,str(path),str(backup),identity['sha256'],identity['size'],stat.S_IMODE(info.st_mode),info.st_mtime_ns,time()+RETENTION,'prepared'))
        try:
            guided.authorized(batch['id']);self.validate(batch,operation)
            move_no_replace(path,stage)
            staged=file_identity(stage,read_guard=self.app.policy.check)
            if staged!=identity:
                move_no_replace(stage,path)
                raise ValueError('A racing file change was preserved; cleanup stopped.')
            # The opaque staged name is not an input chosen by an external caller.
            if file_identity(stage,read_guard=self.app.policy.check)!=identity:raise ValueError('Staging identity changed; manual recovery is required.')
            stage.unlink()
            if path.exists() or stage.exists():raise ValueError('Removal verification failed; inspect the checkpoint.')
            with self.conn:self.conn.execute("UPDATE duplicate_recovery SET state='removed' WHERE id=?",(identifier,))
            journal.complete_operation(guided.conn,receipt,{'path':str(path),'retained':operation['destination'],
                'recovery':identifier,'expires_at':time()+RETENTION},True,read_guard=self.app.policy.check)
            return receipt
        except Exception:
            # Never remove a new occupant or discard an uncertain staging file.
            with self.conn:self.conn.execute("UPDATE duplicate_recovery SET state='manual_recovery_required' WHERE id=?",(identifier,))
            raise

    def prepare_restore(self, job, recovery):
        self.scope(job);record,_=self._recovery_record(recovery)
        original=self.patrol.guided.row(record['batch'])
        if original['job']!=job:raise PermissionError('Recovery belongs to another scope.')
        return self.patrol.guided.prepare_duplicate(job,[{'kind':'dedupe_restore','source':None,'destination':record['source'],
            'recovery':recovery,'reason':'Restore this exact removed copy without overwriting any occupant.'}])

    def recovery_status(self, job):
        self.scope(job)
        batches={r[0] for r in self.patrol.guided.conn.execute('SELECT id FROM guided_batches WHERE job=?',(job,))}
        return [dict(r) for r in self.conn.execute('SELECT id,batch,receipt,source,size,expires,state FROM duplicate_recovery ORDER BY rowid DESC') if r['batch'] in batches]

    def expire(self):
        for record in self.conn.execute("SELECT * FROM duplicate_recovery WHERE expires<? AND state IN ('removed','restored')",(time(),)).fetchall():
            path=Path(record['backup'])
            if path.parent!=self.recovery:continue
            if path.exists():safe_metadata(path);path.unlink()
            with self.conn:self.conn.execute("UPDATE duplicate_recovery SET state='expired' WHERE id=?",(record['id'],))

    def watch(self, job, enabled, read_references=False):
        self.scope(job)
        if type(enabled) is not bool or type(read_references) is not bool:raise ValueError('Use explicit monitoring/reference choices.')
        if enabled:
            if self.watches and job not in self.watches:raise ValueError('Stop the other scoped duplicate monitor first.')
            self.watch_errors.pop(job,None)
            self.watches[job]={'phase':'discover','read_references':read_references}
            self.app.refresh(job);self.begin(job,read_references)
        else:self.watches.pop(job,None)
        self.due=0
        return self.status(job)

    def verify_rule(self, batch_id, identifier):
        batch=self.patrol.guided.row(batch_id);grant=self.grants.get(batch['job'])
        if not grant or grant['id']!=identifier or not self.permission(batch['job'])['automatic']:
            raise PermissionError('The explicit automatic cleanup rule is inactive.')
        for operation in json.loads(batch['payload'])['operations']:
            if operation['kind']!='dedupe_delete' or not is_copy(operation['source'],operation['destination']):
                raise PermissionError('The batch exceeds the authorized copy-suffix rule.')
        return grant

    def tick(self):
        if monotonic()<self.due:return
        self.due=monotonic()+60
        if read_state(self.conn)['paused']:return
        try:self.expire()
        except (OSError,ValueError):return
        for job,watch in list(self.watches.items())[:1]:
            try:
                if watch['phase']=='waiting':
                    self.app.refresh(job);self.begin(job,watch['read_references']);watch['phase']='discover'
                # One bounded discovery/hash checkpoint per minute; no model or OCR runs.
                if not self.audit_step(job):return
                result=self.status(job)['audit'];watch['phase']='waiting'
                grant=self.grants.get(job)
                if not grant or not self.permission(job)['automatic']:return
                assets=[i['id'] for g in result['exact_groups'] for i in g['remove'] if i['automatic_candidate']][:min(20,100-self.auto_count[grant['id']])]
                if not assets:return
                batch=self.prepare(job,result['id'],assets)
                self.patrol.guided.accept_rule(batch['id'],grant['id'])
                self.auto_count[grant['id']]+=len(assets)
                destination=self.patrol.duplicate_destination(job)
                self.patrol._state(destination,'Working','Executing only the explicitly authorized duplicate rule.')
                self.patrol.started[destination]=monotonic()
                self.patrol.wake.set()
            except (OSError,ValueError,OperationTooLarge) as error:
                self.watches.pop(job,None);self.watch_errors[job]=str(error)
