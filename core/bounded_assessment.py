"""On-demand metadata assessment; trusted callers supply read authorization.

No registration or approval is inferred from a path, doctrine or stored run.
Directory attempts are bounded and durable; a killed attempt may be retried once.
Completed observations are never discarded or mistaken for a current snapshot.
"""
import hashlib
import json
import ntpath
import os
from pathlib import Path
import sqlite3
import stat
import time
from datetime import datetime, timezone

from core.media_inventory import safe_metadata, signature
from core.placement import _matching_location, validate_placement_doctrine
from core.read_guard import _local_path, require_path_not_held


def stamp():
    return datetime.now(timezone.utc).isoformat()


def allowed(path, authorize):
    # Reject F before even asking a caller's policy or probing an ancestor.
    normalized = _local_path(path)
    if ntpath.splitdrive(normalized)[0] == 'f:':
        raise PermissionError('F: preservation hold')
    if authorize is None or authorize(str(path)) is not True:
        raise PermissionError('Explicit current metadata-read authority required')
    require_path_not_held(path)


def initialize(conn):
    conn.executescript('''
      CREATE TABLE IF NOT EXISTS assessment_runs (
        id INTEGER PRIMARY KEY, root TEXT NOT NULL, created TEXT NOT NULL,
        doctrine TEXT NOT NULL, doctrine_digest TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS assessment_directories (
        run INTEGER NOT NULL, path TEXT NOT NULL, depth INTEGER NOT NULL,
        state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
        signature TEXT, reason TEXT, PRIMARY KEY(run,path));
      CREATE TABLE IF NOT EXISTS assessment_observations (
        run INTEGER NOT NULL, path TEXT NOT NULL, kind TEXT NOT NULL,
        size INTEGER, mtime_ns INTEGER, observed TEXT NOT NULL,
        PRIMARY KEY(run,path));
    ''')


def start(conn, root, doctrine, authorize):
    allowed(root, authorize)
    root = str(Path(root).absolute())
    allowed(root, authorize)
    info = safe_metadata(root, read_guard=lambda p: allowed(p, authorize))
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError('Assessment scope must be a plain directory')
    validate_placement_doctrine(doctrine)
    encoded = json.dumps(doctrine, sort_keys=True, separators=(',', ':'))
    initialize(conn)
    # Repeated start requests reopen the same retained assessment, not a new scan.
    with conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT id,doctrine FROM assessment_runs WHERE root=? ORDER BY id DESC LIMIT 1', (root,)).fetchone()
        if row:
            if row[1] != encoded:
                raise ValueError('Retained doctrine differs; explicit new assessment review required')
            return row[0]
        run = conn.execute('INSERT INTO assessment_runs(root,created,doctrine,doctrine_digest) VALUES(?,?,?,?)',
                           (root, stamp(), encoded, hashlib.sha256(encoded.encode()).hexdigest())).lastrowid
        conn.execute("INSERT INTO assessment_directories(run,path,depth,state) VALUES(?,?,0,'PENDING')", (run, root))
    return run


def _finish(conn, run, path, state, reason=None):
    with conn:
        conn.execute('UPDATE assessment_directories SET state=?,reason=? WHERE run=? AND path=?',
                     (state, reason, run, path))


def batch(conn, run, authorize, *, max_entries=200, max_directories=5, max_seconds=2, checkpoint=None):
    """One bounded foreground batch. Caller must serialize batches across processes.

    Count limits include repeated enumeration after a crash. Time is cooperative;
    a blocked OS call is not forcibly interrupted here. External termination leaves
    ACTIVE work recoverable, with a two-attempt ceiling and no duplicate records.
    """
    if type(max_entries) is not int or not 1 <= max_entries <= 1000:
        raise ValueError('Entry budget must be 1..1000')
    if type(max_directories) is not int or not 1 <= max_directories <= 10:
        raise ValueError('Directory budget must be 1..10')
    if type(max_seconds) not in (int, float) or not 0 < max_seconds <= 5:
        raise ValueError('Time budget must be >0 and <=5 seconds')
    row = conn.execute('SELECT root FROM assessment_runs WHERE id=?', (run,)).fetchone()
    if not row:
        raise ValueError('Unknown assessment')
    allowed(row[0], authorize)
    started, entries, processed = time.monotonic(), 0, 0
    while processed < max_directories and entries < max_entries and time.monotonic() - started < max_seconds:
        item = conn.execute("SELECT path,depth,attempts,signature FROM assessment_directories WHERE run=? AND state IN ('PENDING','ACTIVE') ORDER BY rowid LIMIT 1", (run,)).fetchone()
        if not item:
            break
        path, depth, attempts, previous_signature = item
        if attempts >= 2:
            _finish(conn, run, path, 'HELD', 'Interrupted twice; automatic retry stopped')
            processed += 1
            continue
        try:
            allowed(path, authorize)
            before = safe_metadata(path, read_guard=lambda p: allowed(p, authorize))
            if not stat.S_ISDIR(before.st_mode):
                raise ValueError('Directory no longer present as a plain directory')
            identity = json.dumps(signature(before))
            if previous_signature and identity != previous_signature:
                raise ValueError('Directory changed since interrupted attempt; coverage unknown')
            with conn:
                conn.execute("UPDATE assessment_directories SET state='ACTIVE',attempts=attempts+1,signature=? WHERE run=? AND path=?", (identity, run, path))
            completed = False
            with os.scandir(path) as iterator:
                while entries < max_entries and time.monotonic() - started < max_seconds:
                    allowed(path, authorize)
                    try:
                        entry = next(iterator)
                    except StopIteration:
                        completed = True
                        break
                    entries += 1
                    allowed(entry.path, authorize)
                    info = safe_metadata(entry.path, read_guard=lambda p: allowed(p, authorize))
                    kind = 'directory' if stat.S_ISDIR(info.st_mode) else 'file' if stat.S_ISREG(info.st_mode) else 'other'
                    with conn:
                        conn.execute('INSERT OR IGNORE INTO assessment_observations VALUES(?,?,?,?,?,?)',
                                     (run, entry.path, kind, info.st_size, info.st_mtime_ns, stamp()))
                        if kind == 'directory':
                            conn.execute('INSERT OR IGNORE INTO assessment_directories(run,path,depth,state,reason) VALUES(?,?,?,?,?)',
                                         (run, entry.path, depth+1, 'PENDING' if depth < 20 else 'HELD',
                                          None if depth < 20 else 'Depth budget; subtree unobserved'))
                    if checkpoint:
                        checkpoint()
            after = safe_metadata(path, read_guard=lambda p: allowed(p, authorize))
            if signature(before) != signature(after):
                raise ValueError('Directory changed during enumeration; retained observations are partial')
            if completed:
                _finish(conn, run, path, 'COMPLETE')
            else:
                # No portable stable scandir cursor exists. Do not repeatedly walk
                # an oversized directory from the beginning under a false resume claim.
                _finish(conn, run, path, 'HELD', 'Batch budget reached inside directory; partial observations retained; no automatic retry')
        except (OSError, ValueError) as exc:
            _finish(conn, run, path, 'HELD', str(exc))
        processed += 1
    result = report(conn, run)
    result['batch'] = {'entries_visited': entries, 'directories_attempted': processed,
                       'seconds': time.monotonic()-started, 'limits': {'entries': max_entries, 'directories': max_directories, 'seconds': max_seconds}}
    return result


def report(conn, run):
    record = conn.execute('SELECT root,created,doctrine,doctrine_digest FROM assessment_runs WHERE id=?', (run,)).fetchone()
    if not record:
        raise ValueError('Unknown assessment')
    root, created, encoded, digest = record
    doctrine = json.loads(encoded)
    states = dict(conn.execute('SELECT state,count(*) FROM assessment_directories WHERE run=? GROUP BY state', (run,)))
    files, size, first, last = conn.execute("SELECT count(*),coalesce(sum(size),0),min(observed),max(observed) FROM assessment_observations WHERE run=? AND kind='file'", (run,)).fetchone()
    groups = {}
    for path, in conn.execute('SELECT path FROM assessment_observations WHERE run=?', (run,)):
        location = _matching_location(doctrine, path)
        key = location['id'] if location else 'unmatched'
        if key not in groups:
            groups[key] = {'location': key, 'count': 0, 'classification': 'UNRESOLVED',
                          'fact': 'No matching placement location', 'inference': 'Purpose and dependencies unknown'}
            if location:
                groups[key].update(fact='Path is inside ' + location['path'],
                                   purpose=location['purpose'], canonicality=location['canonicality'],
                                   classification='RULE_MATCH_NOT_CONTENT_VERDICT',
                                   inference='Location membership is confirmed; content role, intentional exceptions and permanence are unverified')
        groups[key]['count'] += 1
    held = [dict(zip(('path','reason'), r)) for r in conn.execute("SELECT path,reason FROM assessment_directories WHERE run=? AND state='HELD'", (run,))]
    pending = states.get('PENDING', 0) + states.get('ACTIVE', 0)
    return {'id': run, 'scope': root, 'created_at': created, 'first_file_observation': first,
            'last_file_observation': last, 'state': 'PENDING' if pending else 'COMPLETE_WITH_GAPS' if held else 'COMPLETE',
            'directory_states': states, 'files': files, 'bytes': size, 'held': held,
            'coverage_complete': not pending and not held, 'doctrine_digest': digest,
            'placement': list(groups.values()), 'supported_discrepancies': [],
            'limitations': ['Historical metadata traversal, not an atomic or current filesystem snapshot',
                            'No content, dependency, duplicate, canonical-role or intent inspection; no corrective action justified',
                            'Rule membership alone cannot prove semantic congruence or an intentional exception',
                            'OS calls can outlast the cooperative time budget; killed directories retry at most once'],
            'content_reads': 0, 'managed_file_mutations': 0, 'evidence_source': 'assessment_observations',
            'authority': 'Observations and placement rules do not authorize corrective action'}


def historical_baseline(conn, root=r'R:\In_Transit', doctrine=None):
    """Read existing scan evidence only; never probes the source or repairs status."""
    rows = conn.execute('SELECT id,started_at,completed_at,status,files_scanned,last_committed_path FROM scans WHERE lower(root_path)=lower(?) ORDER BY id DESC LIMIT 1', (root,)).fetchone()
    # Normalize literal prefix, not SQL wildcard input supplied by a browser.
    prefix = root.casefold().rstrip('\\/') + '\\'
    count, size, first, last = conn.execute('SELECT count(*),coalesce(sum(size_bytes),0),min(last_seen_at),max(last_seen_at) FROM files WHERE substr(canonical_path,1,?)=?', (len(prefix), prefix)).fetchone()
    branches = {}
    for path, size_bytes in conn.execute('SELECT canonical_path,size_bytes FROM files WHERE substr(canonical_path,1,?)=?', (len(prefix), prefix)):
        parts = path[len(prefix):].split('\\')
        branch = '\\'.join(parts[:3])
        group = branches.setdefault(branch, {'relative_branch': branch, 'files': 0, 'bytes': 0})
        group['files'] += 1
        group['bytes'] += size_bytes or 0
    if doctrine:
        validate_placement_doctrine(doctrine)
        for group in branches.values():
            location = _matching_location(doctrine, prefix + group['relative_branch'])
            group['rule_location'] = location['id'] if location else None
            group['rule_purpose'] = location['purpose'] if location else None
            group['assessment'] = 'Location rule match only; staging intent, permanence and dependencies unresolved'
    return {'scope': root, 'scan': dict(zip(('id','started_at','completed_at','saved_status','files_scanned','last_committed_path'), rows)) if rows else None,
            'retained_files': count, 'retained_bytes': size, 'first_observation_utc': first, 'last_observation_utc': last,
            'branches': list(branches.values()),
            'placement_policy': doctrine.get('placement_policy') if doctrine else None,
            'provenance': 'Existing scans/files ledger; overwritten last_seen_at is not heartbeat or per-scan history',
            'limitations': ['Partial historical ledger coverage; no total or representative coverage established',
                            'Saved running status is not process liveness; no source probes performed']}
