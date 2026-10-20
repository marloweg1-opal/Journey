"""Restartable metadata inventory; sources are read-only and failures stay held."""
import json
import math
import os
from pathlib import Path
import stat
import time

from core.media_recovery import PHOTO, VIDEO, stable_hash


def initialize(conn):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS media_inventory_sources (
            path TEXT PRIMARY KEY COLLATE NOCASE);
        CREATE TABLE IF NOT EXISTS media_source_holds (
            scope TEXT PRIMARY KEY COLLATE NOCASE, reason TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS media_inventory_queue (
            source TEXT NOT NULL, path TEXT NOT NULL COLLATE NOCASE,
            state TEXT NOT NULL DEFAULT 'PENDING', evidence TEXT,
            PRIMARY KEY(source,path));
        CREATE TABLE IF NOT EXISTS media_inventory_files (
            source TEXT NOT NULL, path TEXT NOT NULL COLLATE NOCASE,
            size INTEGER NOT NULL, mtime_ns INTEGER NOT NULL, inode TEXT NOT NULL,
            device TEXT NOT NULL, observed_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY(source,path));
        CREATE TABLE IF NOT EXISTS media_inventory_hashes (
            source TEXT NOT NULL, path TEXT NOT NULL COLLATE NOCASE,
            state TEXT NOT NULL, evidence TEXT NOT NULL,
            PRIMARY KEY(source,path));
    ''')


def hold_source(conn, scope, reason):
    """Persist a no-read hold without probing the affected filesystem."""
    from core.perception_policy import normalize_scope
    scope = normalize_scope(scope)
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError('A source hold requires evidence/reason')
    initialize(conn)
    with conn:
        conn.execute('INSERT OR REPLACE INTO media_source_holds(scope,reason) VALUES(?,?)',
                     (scope, reason.strip()))


def require_read_allowed(conn, path):
    from core.read_guard import require_not_held
    require_not_held(conn, path)


def safe_metadata(path, *, read_guard=None):
    # Reject reparse points on every ancestor, not only the leaf. This is not
    # handle-based race protection; observations never authorize a later move.
    path = Path(path)
    if read_guard is not None:
        read_guard(path)
    for part in (*reversed(path.parents), path):
        if read_guard is not None:
            read_guard(path)
            read_guard(part)
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Reparse/symlink path requires review')
    return info


def register(conn, roots):
    initialize(conn)
    paths = []
    for root in roots:
        require_read_allowed(conn, root)
        path = Path(os.path.abspath(root))
        info = safe_metadata(path)
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError('Inventory source must be a directory')
        paths.append(str(path))
    with conn:
        for path in paths:
            conn.execute('INSERT OR IGNORE INTO media_inventory_sources VALUES(?)', (path,))
            conn.execute('INSERT OR IGNORE INTO media_inventory_queue(source,path) VALUES(?,?)', (path,path))


def signature(info):
    return (info.st_dev, info.st_ino, info.st_mtime_ns)


def _validate_budgets(max_seconds, **counts):
    if any(type(value) is not int or value <= 0 for value in counts.values()):
        raise ValueError('Positive integer count and byte budgets required')
    try:
        valid_time = type(max_seconds) in (int, float) and math.isfinite(max_seconds) and max_seconds > 0
    except OverflowError:
        valid_time = False
    if not valid_time:
        raise ValueError('A finite positive time budget is required')


def batch(conn, *, max_directories=100, max_entries=20000, max_seconds=15, checkpoint=None):
    _validate_budgets(max_seconds, max_directories=max_directories, max_entries=max_entries)
    initialize(conn)
    started = time.monotonic()
    processed = 0
    while processed < max_directories and time.monotonic()-started < max_seconds:
        row = conn.execute("SELECT source,path FROM media_inventory_queue WHERE state='PENDING' ORDER BY rowid LIMIT 1").fetchone()
        if row is None:
            break
        source, directory = row
        files, children, count = [], [], 0
        state, evidence = 'COMPLETE', {}
        try:
            require_read_allowed(conn, source)
            require_read_allowed(conn, directory)
            before = safe_metadata(directory)
            with os.scandir(directory) as entries:
                for entry in entries:
                    count += 1
                    if count > max_entries or time.monotonic()-started >= max_seconds:
                        raise TimeoutError('Directory enumeration exceeded bounded budget; explicit review required')
                    try:
                        require_read_allowed(conn, entry.path)
                    except PermissionError as exc:
                        children.append((source,entry.path,'HELD',json.dumps({'reason':str(exc)})))
                        continue
                    # Windows DirEntry.stat may omit file identity fields.
                    # Use the same lstat identity source as later verification.
                    info = Path(entry.path).lstat()
                    reparse = stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0) & 0x400
                    if reparse:
                        children.append((source,entry.path,'HELD',json.dumps({'reason':'Reparse/symlink not followed'})))
                    elif stat.S_ISDIR(info.st_mode):
                        children.append((source,entry.path,'PENDING',None))
                    elif stat.S_ISREG(info.st_mode) and Path(entry.name).suffix.lower() in PHOTO|VIDEO:
                        files.append((source,entry.path,info.st_size,info.st_mtime_ns,str(info.st_ino),str(info.st_dev)))
            if signature(safe_metadata(directory)) != signature(before):
                raise ValueError('Directory changed during enumeration; cannot assert coverage')
            evidence = {'entries':count,'directory_signature':signature(before),'coverage':'historical bounded enumeration, not a filesystem snapshot'}
        except (OSError, ValueError) as exc:
            state, evidence = 'HELD', {'reason':str(exc),'type':type(exc).__name__,'entries_seen':count}
            files, children = [], []
        # Cursor, occurrences and discovered work share one transaction. A crash
        # before commit leaves this directory pending and safe to enumerate again.
        with conn:
            conn.executemany('INSERT OR IGNORE INTO media_inventory_files(source,path,size,mtime_ns,inode,device) VALUES(?,?,?,?,?,?)',files)
            conn.executemany('INSERT OR IGNORE INTO media_inventory_queue(source,path,state,evidence) VALUES(?,?,?,?)',children)
            conn.execute('UPDATE media_inventory_queue SET state=?,evidence=? WHERE source=? AND path=?', (state,json.dumps(evidence),source,directory))
            if checkpoint:
                checkpoint()
        processed += 1
    return {**summary(conn),'directories_processed_this_batch':processed}


def summary(conn):
    states = dict(conn.execute('SELECT state,count(*) FROM media_inventory_queue GROUP BY state'))
    count, size = conn.execute('SELECT count(*),coalesce(sum(size),0) FROM media_inventory_files').fetchone()
    held = [dict(zip(('source','path','evidence'),r)) for r in conn.execute("SELECT source,path,evidence FROM media_inventory_queue WHERE state='HELD' ORDER BY rowid")]
    hashes = dict(conn.execute('SELECT state,count(*) FROM media_inventory_hashes GROUP BY state'))
    source_holds = [dict(zip(('scope','reason','created_at'), row)) for row in
                    conn.execute('SELECT scope,reason,created_at FROM media_source_holds ORDER BY scope')]
    return {'directory_states':states,'media_occurrences':count,'observed_bytes':size,'hash_states':hashes,
            'source_holds':source_holds,
            'traversal_finished':not states.get('PENDING',0),
            'coverage_complete':not states.get('PENDING',0) and not states.get('HELD',0),
            'coverage_meaning':'historical directory traversal; no absence, current identity, or dependency clearance implied',
            'held':held,'managed_mutations':0,'semantic_inspections':0,
            'estimated_human_decisions':len({r['source'] for r in held})}


def hash_batch(conn, *, max_files=100, max_bytes=256_000_000, max_file_bytes=64_000_000, max_seconds=15):
    """Historical identity evidence only. Failed/oversized files are not retried."""
    _validate_budgets(max_seconds, max_files=max_files, max_bytes=max_bytes, max_file_bytes=max_file_bytes)
    initialize(conn)
    started, consumed, attempted = time.monotonic(), 0, 0
    candidates = conn.execute('''SELECT f.source,f.path,f.size,f.mtime_ns,f.inode,f.device
        FROM media_inventory_files f LEFT JOIN media_inventory_hashes h
        ON f.source=h.source AND f.path=h.path WHERE h.path IS NULL ORDER BY f.rowid LIMIT ?''',(max_files,)).fetchall()
    for source,path,size,mtime,inode,device in candidates:
        remaining = max_seconds-(time.monotonic()-started)
        if remaining <= 0:
            break
        denied = None
        try:
            require_read_allowed(conn, source)
            require_read_allowed(conn, path)
        except (PermissionError, ValueError) as exc:
            denied = {'state':'SOURCE_HELD','reason':str(exc)}
        if denied:
            evidence = denied
        elif size > max_file_bytes:
            evidence = {'state':'BUDGET_HELD','reason':'Per-file byte budget; not a damage verdict'}
        elif consumed+size > max_bytes:
            break
        else:
            try:
                before = safe_metadata(path)
                observed = (before.st_size,before.st_mtime_ns,str(before.st_ino),str(before.st_dev))
                if observed != (size,mtime,inode,device) or not stat.S_ISREG(before.st_mode):
                    evidence = {'state':'CHANGED_SINCE_INVENTORY'}
                else:
                    consumed += size  # Reserve even unsuccessful read attempts.
                    evidence = stable_hash(path,max_bytes=max_file_bytes,max_seconds=remaining)
                    after = safe_metadata(path)
                    if signature(before) != signature(after) or before.st_size != after.st_size:
                        evidence = {'state':'CHANGED_DURING_READ'}
            except (OSError,ValueError) as exc:
                evidence = {'state':'HELD','reason':str(exc)}
        with conn:
            conn.execute('INSERT OR IGNORE INTO media_inventory_hashes VALUES(?,?,?,?)',
                         (source,path,evidence['state'],json.dumps(evidence)))
        attempted += 1
    return {**summary(conn),'hash_attempts_this_batch':attempted,'bytes_reserved_this_batch':consumed}
