"""Durable, bounded discovery and review for Navigator's selected folders."""

from contextlib import ExitStack, closing
from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import sqlite3
import stat
from subprocess import SubprocessError
from tempfile import NamedTemporaryFile
from time import monotonic
from uuid import uuid4

from core.file_paths import safe_metadata, signature
from core.process_lock import ProcessBusyError, process_lock
from core.token_registry import resolve_token
from core.naming import observe_filename
from journey_navigator.context import NAMING_HOLD, assess, preliminary_name, profile_registry
from journey_navigator.links import Boundaries, ProtectedPath, identity, kind_of, path_key, resolve_folder
from journey_navigator.registry import ProjectRegistry, creation_dates, preview as registry_preview
from journey_planner.catalog import File, Plan, absolute_path, check_local_drive, component
from journey_vision.observe import IMAGE_FORMATS, decode_image, describe, image_bytes
from journey_vision.steward import (
    DEFAULT_RULE, SIMILAR, draft_names, pixel_distance, review_index, validate_rule,
)


ENTRY_BATCH = 256
IMAGE_BATCH = 12
TEXT_BATCH = 4
PAGE = 24
SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY, root TEXT NOT NULL, physical_id TEXT NOT NULL, epoch INTEGER NOT NULL,
    rule TEXT NOT NULL, updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS scopes (
    job TEXT NOT NULL, path TEXT NOT NULL, resolution TEXT NOT NULL, grants TEXT NOT NULL, PRIMARY KEY(job,path)
);
CREATE TABLE IF NOT EXISTS scope_access (
    job TEXT NOT NULL, path TEXT NOT NULL, parent TEXT, inspect INTEGER NOT NULL, propose INTEGER NOT NULL,
    PRIMARY KEY(job,path)
);
CREATE TABLE IF NOT EXISTS dirs (
    job TEXT NOT NULL, physical_id TEXT NOT NULL, path TEXT NOT NULL, scope TEXT NOT NULL, epoch INTEGER NOT NULL,
    status TEXT NOT NULL, PRIMARY KEY(job,physical_id)
);
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY, job TEXT NOT NULL, key TEXT NOT NULL, path TEXT NOT NULL, scope TEXT NOT NULL,
    epoch INTEGER NOT NULL, size INTEGER NOT NULL, modified INTEGER NOT NULL, status TEXT NOT NULL,
    digest TEXT, series TEXT, reason TEXT NOT NULL DEFAULT '', reused INTEGER NOT NULL DEFAULT 0, UNIQUE(job,key)
);
CREATE TABLE IF NOT EXISTS observations (
    job TEXT NOT NULL, scope TEXT NOT NULL, digest TEXT NOT NULL, features TEXT NOT NULL, bucket TEXT NOT NULL,
    representative INTEGER NOT NULL, series TEXT NOT NULL, ocr_key TEXT, ocr TEXT, PRIMARY KEY(job,scope,digest)
);
CREATE TABLE IF NOT EXISTS links (
    id INTEGER PRIMARY KEY, job TEXT NOT NULL, key TEXT NOT NULL, path TEXT NOT NULL, kind TEXT NOT NULL,
    scope TEXT NOT NULL, epoch INTEGER NOT NULL, record TEXT NOT NULL, UNIQUE(job,key)
);
CREATE TABLE IF NOT EXISTS gaps (
    job TEXT NOT NULL, path TEXT NOT NULL, epoch INTEGER NOT NULL, reason TEXT NOT NULL, scope TEXT, PRIMARY KEY(job,path)
);
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY, job TEXT NOT NULL, event TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS asset_transitions (
    id INTEGER PRIMARY KEY,job TEXT NOT NULL,scope TEXT NOT NULL,digest TEXT NOT NULL,
    from_path TEXT NOT NULL,to_path TEXT NOT NULL,receipt INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS directory_queue ON dirs(job,epoch,status);
CREATE INDEX IF NOT EXISTS file_queue ON files(job,epoch,status,id);
CREATE INDEX IF NOT EXISTS scoped_visual_buckets ON observations(job,scope,bucket,representative);
CREATE INDEX IF NOT EXISTS file_series ON files(job,epoch,series,id);
CREATE INDEX IF NOT EXISTS file_content ON files(job,epoch,scope,digest);
"""


def _prepare_data_dir(folder):
    folder = absolute_path(folder)
    check_local_drive(folder)
    missing = []
    current = folder
    while True:
        try:
            if not stat.S_ISDIR(safe_metadata(current).st_mode):
                raise ValueError("Journey's review storage needs a folder.")
            break
        except FileNotFoundError:
            missing.append(current)
            current = current.parent
    for path in reversed(missing):
        path.mkdir(exist_ok=True)
        safe_metadata(path)
    return folder.resolve(strict=True)


def _message(error):
    if isinstance(error, PermissionError) and not isinstance(error, ProtectedPath):
        return "The operating system denied access."
    if isinstance(error, (FileNotFoundError, NotADirectoryError)):
        return "The path disappeared or is no longer a folder."
    return str(error)


def _markers(values):
    return ",".join("?" for _ in values)


def _series(scope, digest):
    return sha256(f"{scope}\0{digest}".encode()).hexdigest()


class Workbench:
    def __init__(self, data_dir, *, blocked=(), hold_store=None, perception_store=None, ocr=None, temporary=False):
        self.retains = not temporary
        self.data_dir = absolute_path(data_dir) if temporary else _prepare_data_dir(data_dir)
        self.policy = Boundaries((self.data_dir, *blocked), hold_store=hold_store, perception_store=perception_store)
        self.database = self.data_dir / "navigator-inspection.sqlite"
        self.ocr = ocr
        self.registry = profile_registry()
        lock_path = self.data_dir / "navigator-inspection.lock"
        sidecars = [self.database.with_name(self.database.name + suffix) for suffix in ("", "-journal", "-wal", "-shm")]
        with ExitStack() as setup:
            if self.retains:
                for path in (lock_path, *sidecars):
                    if os.path.lexists(path) and not stat.S_ISREG(safe_metadata(path).st_mode):
                        raise ValueError("Journey's review storage contains an unexpected file type.")
                try:
                    setup.enter_context(process_lock(lock_path))
                except ProcessBusyError as error:
                    raise ValueError("This review storage is already open in another Navigator session.") from error
            self.conn = setup.enter_context(closing(sqlite3.connect(self.database if self.retains else ":memory:", check_same_thread=False)))
            self.conn.row_factory = sqlite3.Row
            self.conn.create_function("scoped_series", 2, _series, deterministic=True)
            self.conn.execute("PRAGMA secure_delete=ON")
            self.conn.execute("PRAGMA temp_store=MEMORY")
            self.conn.executescript(SCHEMA)
            self._upgrade_checkpoint()
            self.project_registry = ProjectRegistry(self)
            self.resources = setup.pop_all()
        self.tickets = {}
        self.cursor = None

    def close(self):
        self.pause()
        self.resources.close()

    def _upgrade_checkpoint(self):
        # Legacy checkpoints are listed for reselection, with their access inactive.
        # Their pixel records are attributed to each original scope before reuse.
        with self.conn:
            if self.conn.execute("SELECT 1 FROM sqlite_schema WHERE type='table' AND name='cache'").fetchone():
                self.conn.execute("""INSERT OR IGNORE INTO observations(job,scope,digest,features,bucket,representative,series)
                    SELECT f.job,f.scope,c.digest,c.features,c.bucket,1,scoped_series(f.scope,c.digest) FROM files f
                    JOIN cache c ON c.job=f.job AND c.digest=f.digest""")
                self.conn.execute("UPDATE files SET series=scoped_series(scope,digest) WHERE digest IS NOT NULL")
                self.conn.execute("DROP TABLE cache")
            columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(gaps)")}
            if "scope" not in columns:
                self.conn.execute("ALTER TABLE gaps ADD COLUMN scope TEXT")
                self.conn.execute("DELETE FROM gaps")

    def pause(self):
        if self.cursor:
            self.cursor[1].close()
            self.cursor = None

    def jobs(self):
        return [dict(row) for row in self.conn.execute("""SELECT j.id,j.root,j.updated,coalesce(a.inspect,0) AS active
            FROM jobs j LEFT JOIN scope_access a ON a.job=j.id AND a.path=j.root ORDER BY j.updated DESC LIMIT 100""")]

    def job(self, job_id):
        row = self.conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise ValueError("Select a saved review first.")
        return row

    def browse(self, selected, offset=0):
        self.policy.refresh()
        resolved = resolve_folder(absolute_path(selected), self.policy)
        if resolved.status != "ready" or resolved.hops:
            raise ValueError(resolved.reason or "Review a linked folder before opening its destination.")
        folder = Path(resolved.target)
        rows = []
        examined = 0
        with os.scandir(folder) as entries:
            for entry in entries:
                path = Path(entry.path)
                try:
                    self.policy.check(path)
                    kind = kind_of(path, entry.stat(follow_symlinks=False))
                except (OSError, ValueError):
                    continue
                if kind == "file":
                    continue
                examined += 1
                if examined > offset:
                    rows.append({"path": str(path), "name": path.name, "kind": kind})
                if len(rows) > 100:
                    break
        return {"folder": str(folder), "parent": str(folder.parent), "entries": rows[:100], "more": len(rows) > 100}

    def select(self, value, *, job_id=None, link_id=None, proposals=False):
        if type(proposals) is not bool:
            raise ValueError("Choose whether this inspection may suggest changes.")
        self.policy.refresh()
        allowed = ()
        if job_id is not None:
            job = self.job(job_id)
            row = self.conn.execute("SELECT * FROM links WHERE job=? AND id=? AND epoch=?",
                                    (job_id, link_id, job["epoch"])).fetchone()
            if row is None:
                raise ValueError("This link is outside the current scan.")
            self._validate_scope(job, row["scope"])
            value, allowed = row["path"], (job["root"], row["scope"])
        result = resolve_folder(absolute_path(value), self.policy, allowed)
        if job_id is not None and result.status == "ready" and result.hops and self._cycle(job, Path(value), Path(result.target)):
            result.status, result.reason = "cycle", "This destination would lead back through an earlier folder."
        return self._selection(result, allowed, job_id, link_id, proposals)

    def approve(self, ticket, *, proposals=None):
        self.policy.refresh()
        data = self.tickets.pop(ticket, None)
        if not data or data[-1] < monotonic():
            raise ValueError("This link review expired. Select the link again.")
        preview, grants, job_id, link_id, original_proposals, _ = data
        if proposals is None:
            proposals = original_proposals
        if type(proposals) is not bool:
            raise ValueError("Choose whether this destination may suggest changes.")
        if job_id is not None:
            job = self.job(job_id)
            row = self.conn.execute("SELECT scope FROM links WHERE job=? AND id=? AND epoch=?",
                                    (job_id, link_id, job["epoch"])).fetchone()
            if row is None:
                raise ValueError("This link is outside the current scan.")
            self._validate_scope(job, row["scope"])
        current = resolve_folder(Path(preview.selected), self.policy, grants)
        if current != preview:
            raise ValueError("The link changed after the destination was shown. Select it again.")
        grants = (*grants, current.target)
        result = resolve_folder(Path(current.selected), self.policy, grants)
        if result.hops[:len(current.hops)] != current.hops:
            raise ValueError("The link changed during authorization. Select it again.")
        if job_id is not None and result.status == "ready" and self._cycle(job, Path(result.selected), Path(result.target)):
            result.status, result.reason = "cycle", "This destination would lead back through an earlier folder."
        return self._selection(result, grants, job_id, link_id, proposals)

    def _selection(self, result, grants, job_id, link_id, proposals):
        if result.status in ("ready", "approval_required") and Path(result.target).parent == Path(result.target):
            raise ProtectedPath("Choose a project folder within the drive. Journey requires a narrower inspection scope.")
        response = result.record()
        if result.status == "approval_required":
            self.tickets = {key: value for key, value in self.tickets.items() if value[-1] >= monotonic()}
            if len(self.tickets) >= 64:
                self.tickets.pop(next(iter(self.tickets)))
            ticket = ("" if self.retains else "session-") + secrets.token_urlsafe(24)
            self.tickets[ticket] = (result, grants, job_id, link_id, proposals, monotonic() + 300)
            response["ticket"] = ticket
            response["retains"] = self.retains
            response["proposals"] = proposals
        if result.status != "ready":
            if link_id is not None:
                with self.conn:
                    self.conn.execute("UPDATE links SET record=? WHERE job=? AND id=?", (json.dumps(response | {"ticket": None}), job_id, link_id))
            return response
        root = Path(result.target)
        if self.data_dir.is_relative_to(root):
            raise ValueError("Choose a project folder outside Journey's review storage.")
        direct_selection = job_id is None
        if direct_selection:
            job_id = sha256(result.physical_id.encode()).hexdigest()[:24]
            if not self.retains:
                job_id = "session-" + job_id
            existing = self.conn.execute("SELECT root FROM jobs WHERE id=?", (job_id,)).fetchone()
            if existing and Path(existing["root"]) != root:
                # Keep prior review history if the physical directory has been moved.
                job_id = sha256((result.physical_id + path_key(root)).encode()).hexdigest()[:24]
                if not self.retains:
                    job_id = "session-" + job_id
        with self.conn:
            self.conn.execute("INSERT OR IGNORE INTO jobs(id,root,physical_id,epoch,rule) VALUES(?,?,?,1,?)",
                              (job_id, result.target, result.physical_id, json.dumps(DEFAULT_RULE)))
            job = self.job(job_id)
            self.conn.execute("UPDATE jobs SET updated=CURRENT_TIMESTAMP WHERE id=?", (job_id,))
            origin = self.conn.execute("SELECT scope FROM links WHERE job=? AND id=?", (job_id, link_id)).fetchone()
            source_scope = origin["scope"] if origin else None
            covering = next((scope for scope in (source_scope, job["root"]) if scope and root.is_relative_to(scope)), None)
            scope = result.target if direct_selection or covering is None else covering
            if direct_selection or covering is None:
                if self.conn.execute("SELECT count(*) FROM scopes WHERE job=?", (job_id,)).fetchone()[0] >= 64 and not direct_selection:
                    raise ValueError("This inspection already has 64 scopes. Open the destination as a separate review.")
                self.conn.execute("INSERT OR REPLACE INTO scopes VALUES(?,?,?,?)",
                                  (job_id, scope, json.dumps(result.record()), json.dumps(grants)))
                self.conn.execute("INSERT OR REPLACE INTO scope_access VALUES(?,?,?,1,?)",
                                  (job_id, scope, source_scope, proposals))
            added = self._queue_dir(job, result.physical_id, result.target, scope)
            if result.hops:
                if not added:
                    result.status = "already_covered"
                    result.reason = "This physical folder already has a discovery record."
                self._record_link(job, result.selected, result.hops[0]["kind"], source_scope or scope, result)
        return response | {"job": job_id}

    def _queue_dir(self, job, physical_id, path, scope):
        return self.conn.execute("""INSERT INTO dirs VALUES(?,?,?,?,?,'pending')
            ON CONFLICT(job,physical_id) DO UPDATE SET path=excluded.path,scope=excluded.scope,epoch=excluded.epoch,status='pending'
            WHERE dirs.epoch<>excluded.epoch""", (job["id"], physical_id, path, scope, job["epoch"])).rowcount != 0

    def _validate_scope(self, job, scope, *, ancestry=()):
        row = self.conn.execute("""SELECT s.resolution,s.grants,a.parent,a.inspect,a.propose FROM scopes s
            JOIN scope_access a ON a.job=s.job AND a.path=s.path WHERE s.job=? AND s.path=?""",
            (job["id"], scope)).fetchone()
        if row is None or not row["inspect"] or scope in ancestry:
            raise ProtectedPath("Inspection permission is inactive. Choose and authorize the folder again.")
        if row["parent"]:
            self._validate_scope(job, row["parent"], ancestry=(*ancestry, scope))
        prior = json.loads(row["resolution"])
        result = resolve_folder(Path(prior["selected"]), self.policy, json.loads(row["grants"]))
        if result.record() != prior:
            raise ProtectedPath("The saved source or link changed. Select it again to verify the destination.")
        return bool(row["propose"])

    def _visible(self, job):
        self.policy.refresh()
        self._validate_scope(job, job["root"])
        visible = [job["root"]]
        for row in self.conn.execute("SELECT path FROM scope_access WHERE job=? AND inspect=1 AND path<>?",
                                     (job["id"], job["root"])):
            try:
                self._validate_scope(job, row["path"])
            except ProtectedPath:
                continue
            visible.append(row["path"])
        return visible

    def permissions(self, job_id):
        job = self.job(job_id)
        scopes = self.conn.execute("""SELECT s.path,coalesce(a.inspect,0) AS inspect,coalesce(a.propose,0) AS propose
            FROM scopes s LEFT JOIN scope_access a ON a.job=s.job AND a.path=s.path WHERE s.job=? ORDER BY s.path""", (job_id,))
        return {"root": job["root"], "retains": self.retains,
                "scopes": [dict(row) | {"retain": self.retains, "reuse_elsewhere": False, "execute": False} for row in scopes]}

    def permit_proposals(self, job_id, scope, allowed):
        if type(allowed) is not bool:
            raise ValueError("Choose whether this folder may suggest changes.")
        self.policy.refresh()
        self._validate_scope(self.job(job_id), scope)
        with self.conn:
            self.conn.execute("UPDATE scope_access SET propose=? WHERE job=? AND path=?", (allowed, job_id, scope))
        return self.permissions(job_id)

    def revoke(self, job_id, scope, permission):
        job = self.job(job_id)
        if permission not in ("inspect", "retain"):
            raise ValueError("Choose to revoke inspection or forget retained data.")
        if not self.conn.execute("SELECT 1 FROM scopes WHERE job=? AND path=?", (job_id, scope)).fetchone():
            raise ValueError("Choose an existing scope in this review.")
        affected = [row[0] for row in self.conn.execute("""WITH RECURSIVE affected(path) AS (
            SELECT ? UNION SELECT a.path FROM scope_access a JOIN affected p ON a.parent=p.path WHERE a.job=?
        ) SELECT path FROM affected""", (scope, job_id))]
        if scope == job["root"]:
            affected = [row[0] for row in self.conn.execute("SELECT path FROM scopes WHERE job=?", (job_id,))]
        self.pause()
        self.tickets.clear()
        markers, params = _markers(affected), (job_id, *affected)
        if permission == 'retain':
            from journey_navigator.migrations import clear_inspection_backups
            clear_inspection_backups(self.data_dir)
        with self.conn:
            self.conn.execute(f"UPDATE scope_access SET inspect=0,propose=0 WHERE job=? AND path IN ({markers})", params)
            self.conn.execute(f"""UPDATE links SET record=json_set(record,'$.status','approval_required',
                '$.physical_id','','$.reason','Inspection permission for this destination was revoked.')
                WHERE job=? AND json_extract(record,'$.target') IN ({markers}) AND json_extract(record,'$.status') IN ('ready','already_covered')""", params)
            if permission == "retain":
                self.conn.execute(f'DELETE FROM asset_transitions WHERE job=? AND scope IN ({markers})',params)
                tables={row[0] for row in self.conn.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
                if 'patrol_assets' in tables:
                    self.conn.execute(f"""DELETE FROM virtual_memberships WHERE asset IN
                        (SELECT asset FROM patrol_assets WHERE json_extract(record,'$.scope') IN ({markers}))""",affected)
                    self.conn.execute(f"DELETE FROM patrol_assets WHERE json_extract(record,'$.scope') IN ({markers})",affected)
                    self.conn.execute('DELETE FROM patrol_questions WHERE destination IN (SELECT id FROM destinations WHERE job=?)',(job_id,))
                    if scope==job['root']:
                        for table in ('patrol_tasks','virtual_collections','virtual_memberships','destination_outcomes'):
                            if table in tables:
                                self.conn.execute(f'DELETE FROM {table} WHERE destination IN (SELECT id FROM destinations WHERE job=?)',(job_id,))
                        self.conn.execute('DELETE FROM destinations WHERE job=?',(job_id,))
                for table in ("dirs", "files", "observations", "links", "gaps"):
                    self.conn.execute(f"DELETE FROM {table} WHERE job=? AND scope IN ({markers})", params)
                self.conn.execute(f"DELETE FROM reviews WHERE job=? AND json_extract(event,'$.scope') IN ({markers})", params)
                for table in ("scopes", "scope_access"):
                    self.conn.execute(f"DELETE FROM {table} WHERE job=? AND path IN ({markers})", params)
                if scope == job["root"]:
                    self.project_registry.forget(job_id)
                    self.conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        return {"revoked": affected, "closed": scope == job["root"]}

    def refresh(self, job_id):
        self.policy.refresh()
        job = self.job(job_id)
        self._validate_scope(job, job["root"])
        self.pause()
        with self.conn:
            self.conn.execute("UPDATE jobs SET epoch=epoch+1,updated=CURRENT_TIMESTAMP WHERE id=?", (job_id,))
            job = self.job(job_id)
            for row in self.conn.execute("SELECT path,resolution FROM scopes WHERE job=?", (job_id,)).fetchall():
                try:
                    self._validate_scope(job, row["path"])
                except ProtectedPath:
                    continue
                source = json.loads(row["resolution"])
                self._queue_dir(job, source["physical_id"], row["path"], row["path"])
                if source["hops"]:
                    self.conn.execute("UPDATE links SET epoch=? WHERE job=? AND key=?",
                                      (job["epoch"], job_id, path_key(source["selected"])))
        return self.summary(job_id)

    def _record_link(self, job, path, kind, scope, result):
        self.conn.execute("""INSERT INTO links(job,key,path,kind,scope,epoch,record) VALUES(?,?,?,?,?,?,?)
            ON CONFLICT(job,key) DO UPDATE SET kind=excluded.kind,scope=excluded.scope,epoch=excluded.epoch,record=excluded.record""",
                          (job["id"], path_key(path), path, kind, scope, job["epoch"], json.dumps(result.record())))

    def _cycle(self, job, path, target):
        pending, visited = [target], set()
        edges = [(Path(origin).parent, Path(destination)) for origin, destination in self.conn.execute("""SELECT path,json_extract(record,'$.target')
            FROM links WHERE job=? AND epoch=? AND key<>? AND json_extract(record,'$.status') IN ('ready','already_covered')""",
            (job["id"], job["epoch"], path_key(path)))]
        while pending:
            root = pending.pop()
            if root in visited:
                continue
            if path.parent.is_relative_to(root):
                return True
            visited.add(root)
            pending.extend(destination for origin, destination in edges if origin.is_relative_to(root))
        return False

    def _gap(self, job, scope, path, reason):
        self.conn.execute("INSERT OR REPLACE INTO gaps(job,path,epoch,reason,scope) VALUES(?,?,?,?,?)",
                          (job["id"], str(path), job["epoch"], reason, scope))

    def _discover_entry(self, job, scope, entry):
        path = Path(entry.path)
        try:
            self.policy.check(path)
            info = entry.stat(follow_symlinks=False)
            kind = kind_of(path, info)
            if kind == "folder":
                self._queue_dir(job, identity(path.lstat()), str(path), scope)
            elif kind != "file":
                prior = self.conn.execute("""SELECT s.* FROM scopes s JOIN scope_access a ON a.job=s.job AND a.path=s.path
                    WHERE s.job=? AND a.inspect=1 AND json_extract(s.resolution,'$.selected')=?""", (job["id"], str(path))).fetchone()
                result = resolve_folder(path, self.policy, (job["root"], scope))
                if prior and result.status == "approval_required":
                    try:
                        self._validate_scope(job, prior["path"])
                    except ProtectedPath:
                        prior = None
                    else:
                        result = resolve_folder(path, self.policy, json.loads(prior["grants"]))
                if result.status == "ready":
                    if self._cycle(job, path, Path(result.target)):
                        result.status, result.reason = "cycle", "This destination would lead back through an earlier folder."
                    elif not self._queue_dir(job, result.physical_id, result.target,
                                             prior["path"] if prior and result.target == prior["path"] else
                                             scope if Path(result.target).is_relative_to(scope) else job["root"]):
                        result.status, result.reason = "already_covered", "This physical folder already has a discovery record."
                self._record_link(job, str(path), kind, scope, result)
            elif stat.S_ISREG(info.st_mode):
                status = "pending" if path.suffix.casefold() in IMAGE_FORMATS else "unsupported"
                self.conn.execute("""INSERT INTO files(job,key,path,scope,epoch,size,modified,status) VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(job,key) DO UPDATE SET scope=excluded.scope,epoch=excluded.epoch,size=excluded.size,modified=excluded.modified,
                    status=excluded.status,reused=0,digest=NULL,series=NULL,reason=''
                    WHERE files.epoch<>excluded.epoch""", (job["id"], path_key(path), str(path), scope, job["epoch"], info.st_size, info.st_mtime_ns, status))
            else:
                self._gap(job, scope, path, "This is a special filesystem entry.")
        except (OSError, ValueError) as error:
            self._gap(job, scope, path, _message(error))

    def _discover(self, job, checked):
        row = self.conn.execute("SELECT * FROM dirs WHERE job=? AND epoch=? AND status='pending' ORDER BY rowid LIMIT 1",
                                (job["id"], job["epoch"])).fetchone()
        if row is None:
            return
        path, key = Path(row["path"]), (job["id"], job["epoch"], row["physical_id"])
        try:
            self._check_scope(job, row["scope"], checked)
            self.policy.check(path)
            before = safe_metadata(path, read_guard=self.policy.check)
            if identity(before) != row["physical_id"] or not path.is_relative_to(row["scope"]):
                raise ProtectedPath("The folder changed after it was discovered.")
            if self.cursor is None or self.cursor[0] != key or self.cursor[2] != signature(before):
                self.pause()
                self.cursor = (key, os.scandir(path), signature(before))
            self.conn.execute("SAVEPOINT directory_batch")
            try:
                for _ in range(ENTRY_BATCH):
                    entry = next(self.cursor[1], None)
                    if entry is None:
                        self.pause()
                        self.conn.execute("UPDATE dirs SET status='done' WHERE job=? AND physical_id=?", (job["id"], row["physical_id"]))
                        break
                    self._discover_entry(job, row["scope"], entry)
                if signature(safe_metadata(path, read_guard=self.policy.check)) != signature(before):
                    raise ProtectedPath("The folder changed during inspection. Refresh to read it again.")
            except (OSError, ValueError, sqlite3.Error):
                self.pause()
                self.conn.execute("ROLLBACK TO directory_batch")
                raise
            finally:
                self.conn.execute("RELEASE directory_batch")
        except (OSError, ValueError) as error:
            self.pause()
            self._gap(job, row["scope"], path, _message(error))
            self.conn.execute("UPDATE dirs SET status='skipped' WHERE job=? AND physical_id=?", (job["id"], row["physical_id"]))

    def _check_scope(self, job, scope, checked):
        if scope not in checked:
            self._validate_scope(job, scope)
            checked.add(scope)

    def _analyze(self, job, row, checked):
        from PIL import Image

        path = Path(row["path"])
        try:
            self._check_scope(job, row["scope"], checked)
            self.policy.check_image(path, retain=self.retains)
            if not path.is_relative_to(row["scope"]):
                raise ProtectedPath("The image is outside the verified folder.")
            data = image_bytes(path, File(row["size"], row["modified"], path.name))
            digest = sha256(data).hexdigest()
            key = (job["id"], row["scope"], digest)
            cached = self.conn.execute("SELECT * FROM observations WHERE job=? AND scope=? AND digest=?", key).fetchone()
            fmt = IMAGE_FORMATS[path.suffix.casefold()]
            image = None
            if cached:
                features = json.loads(cached["features"])
                if features["format"] != fmt:
                    raise ValueError("This image's contents and filename extension disagree.")
                if "creation_dates" not in features:
                    features["creation_dates"] = creation_dates(data)
                    self.conn.execute("UPDATE observations SET features=? WHERE job=? AND scope=? AND digest=?",
                                      (json.dumps(features), *key))
                series = cached["series"]
            else:
                image = decode_image(data, fmt)
                features = describe(image) | {"format": fmt, "creation_dates": creation_dates(data)}
                ratio = features["width"] / features["height"]
                bucket = f"{round(min(ratio, 3) * 4)}:{int(features['transparency'] >= .23)}"
                candidates = self.conn.execute("""SELECT series,features FROM observations
                    WHERE job=? AND scope=? AND bucket=? AND representative=1 ORDER BY digest LIMIT 32""",
                    (job["id"], row["scope"], bucket)).fetchall()
                new_series = _series(row["scope"], digest)
                score, series = min(((pixel_distance(features, json.loads(example["features"])), example["series"])
                                     for example in candidates), default=(1, new_series))
                if score > SIMILAR:
                    series = new_series
                self.conn.execute("""INSERT INTO observations(job,scope,digest,features,bucket,representative,series)
                    VALUES(?,?,?,?,?,?,?)""", (*key, json.dumps(features), bucket, series == new_series, series))
            if self.ocr and (not cached or cached["ocr_key"] != self.ocr.key):
                if image is None:
                    image = decode_image(data, fmt)
                try:
                    ocr = self.ocr.recognize(image)
                except (OSError, ValueError, SubprocessError):
                    ocr = {"status": "retry", "provider": self.ocr.version}
                self.conn.execute("UPDATE observations SET ocr_key=?,ocr=? WHERE job=? AND scope=? AND digest=?",
                                  (self.ocr.key if ocr["status"] != "retry" else None, json.dumps(ocr), *key))
            self.conn.execute("UPDATE files SET status='analyzed',digest=?,series=?,reused=? WHERE id=?", (digest, series, bool(cached), row["id"]))
        except (OSError, ValueError, Image.DecompressionBombError) as error:
            self.conn.execute("UPDATE files SET status='skipped',reason=? WHERE id=?", (_message(error), row["id"]))

    def step(self, job_id):
        self.policy.refresh()
        job = self.job(job_id)
        self._validate_scope(job, job["root"])
        checked = {job["root"]}
        with self.conn:
            for _ in range(12):
                self._discover(job, checked)
                if self.cursor is not None:
                    break
            rows = self.conn.execute("SELECT * FROM files WHERE job=? AND epoch=? AND status='pending' ORDER BY id LIMIT ?",
                                     (job_id, job["epoch"], TEXT_BATCH if self.ocr else IMAGE_BATCH)).fetchall()
            for row in rows:
                self._analyze(job, row, checked)
        return self.summary(job_id)

    def summary(self, job_id):
        job = self.job(job_id)
        visible = self._visible(job)
        params = (job_id, job["epoch"], *visible)
        active = f"job=? AND epoch=? AND scope IN ({_markers(visible)})"
        counts = dict(self.conn.execute(f"SELECT status,count(*) FROM files WHERE {active} GROUP BY status", params))
        folders = dict(self.conn.execute(f"SELECT status,count(*) FROM dirs WHERE {active} GROUP BY status", params))
        reused, = self.conn.execute(f"SELECT count(*) FROM files WHERE {active} AND reused=1", params).fetchone()
        gaps, = self.conn.execute(f"SELECT count(*) FROM gaps WHERE {active}", params).fetchone()
        links, attention = self.conn.execute(f"""SELECT count(*),sum(json_extract(record,'$.status') NOT IN ('ready','already_covered'))
            FROM links WHERE {active}""", params).fetchone()
        text_count, = self.conn.execute(f"""SELECT count(*) FROM files WHERE {active} AND status='analyzed' AND EXISTS(
            SELECT 1 FROM observations o WHERE o.job=files.job AND o.scope=files.scope AND o.digest=files.digest
            AND json_extract(o.ocr,'$.status')='read')""", params).fetchone()
        proposals = self.conn.execute("SELECT propose FROM scope_access WHERE job=? AND path=?", (job_id, job["root"])).fetchone()[0]
        return {"id": job_id, "root": job["root"], "files": sum(counts.values()), "folders": sum(folders.values()),
                "analyzed": counts.get("analyzed", 0), "pending": counts.get("pending", 0), "unsupported": counts.get("unsupported", 0),
                "pending_folders": folders.get("pending", 0), "reused": reused, "skipped": gaps + counts.get("skipped", 0),
                "links": links, "link_attention": attention or 0, "rule": json.loads(job["rule"]),
                "retains": self.retains, "proposals": bool(proposals), "text_count": text_count, "ocr_available": bool(self.ocr)}

    def links(self, job_id, offset):
        job = self.job(job_id)
        visible = self._visible(job)
        rows = self.conn.execute(f"""SELECT * FROM links WHERE job=? AND epoch=? AND scope IN ({_markers(visible)})
            ORDER BY id LIMIT ? OFFSET ?""", (job_id, job["epoch"], *visible, PAGE + 1, offset)).fetchall()
        return {"items": [json.loads(row["record"]) | {"id": row["id"], "kind": row["kind"]} for row in rows[:PAGE]],
                "more": len(rows) > PAGE}

    def issues(self, job_id, offset):
        job = self.job(job_id)
        visible = self._visible(job)
        key = (job_id, job["epoch"], *visible)
        active = f"job=? AND epoch=? AND scope IN ({_markers(visible)})"
        rows = self.conn.execute(f"""SELECT path,reason FROM gaps WHERE {active}
            UNION ALL SELECT path,reason FROM files WHERE {active} AND status='skipped'
            ORDER BY path LIMIT ? OFFSET ?""", (*key, *key, PAGE + 1, offset)).fetchall()
        return {"items": [dict(row) for row in rows[:PAGE]], "more": len(rows) > PAGE}

    def _reviews(self, job, scope):
        events = [json.loads(row[0]) for row in self.conn.execute("""SELECT event FROM reviews
            WHERE job=? AND json_extract(event,'$.scope')=? ORDER BY id""", (job["id"], scope))]
        cache = {}
        allowed = []
        for event in events:
            try:
                self.policy.check_image(Path(event["source_path"]), retain=self.retains, learn=True)
            except ProtectedPath:
                continue
            allowed.append(event)
            if event["digest"] in cache:
                continue
            row = self.conn.execute("SELECT features FROM observations WHERE job=? AND scope=? AND digest=?",
                                    (job["id"], scope, event["digest"])).fetchone()
            if row:
                cache[event["digest"]] = {"features": json.loads(row["features"])}
        identities,purposes=review_index([event for event in allowed if event["digest"] in cache])
        for transition in self.conn.execute('SELECT * FROM asset_transitions WHERE job=? AND scope=? ORDER BY id',(job['id'],scope)):
            source=(Path(transition['from_path']).as_posix(),transition['digest'])
            if source in purposes:
                purposes[(Path(transition['to_path']).as_posix(),transition['digest'])]=purposes[source]
        return (identities,purposes), cache

    def _image_view(self, job, row, reviews, evidence, *, thumbnails, proposals, profile):
        path = self.policy.check_image(Path(row["path"]), retain=self.retains)
        features = json.loads(row["features"])
        asset = {"digest": row["digest"], "features": features}
        ocr = json.loads(row["ocr"]) if row["ocr"] else {"status": "pending_refresh" if self.ocr else "unavailable"}
        if self.ocr and row["ocr_key"] and row["ocr_key"] != self.ocr.key:
            ocr["refresh_available"] = True
        record = assess(self.registry, path, row["scope"], asset, reviews, evidence, ocr)
        memberships = [f"Visual series {row['series'][:8]}"]
        if record["purpose"]["label"]:
            memberships.append(record["purpose"]["label"])
        if record["identity"]["label"]:
            memberships.append(f"{record['identity']['state'].replace('_', ' ')} · {record['identity']['label']}")
        rule = json.loads(job["rule"])
        record["suggestion"] = preliminary_name(path, record, rule) if proposals else None
        record["name"] = {"state": "disabled", "destination": None, "reason": "Name and plan suggestions are disabled for this scope."}
        naming_rule, metadata = self.project_registry.details(job, row, features, profile, record)
        if proposals and profile:
            record["name"] = registry_preview(path, record, metadata, naming_rule)
            if record["name"]["destination"]:
                record["name"]["destination"] = path.with_name(record["name"]["destination"]).relative_to(row["scope"]).as_posix()
        elif proposals:
            relative = path.relative_to(row["scope"]).as_posix()
            draft = Plan(row["scope"], "", files={relative: File(row["size"], row["modified"], path.name)})
            draft_names(draft, {relative: record}, rule)
            if record["name"].get("destination"):
                record["name"].update(state="held_convention", candidate_destination=record["name"]["destination"],
                                      destination=None, blocker=NAMING_HOLD, executable=False)
        if record["name"]["state"] == "proposed":
            target = Path(row["scope"]) / record["name"]["destination"]
            try:
                self.policy.check(target)
                if os.path.lexists(target):
                    raise ValueError("That destination is already occupied. Review the competing asset.")
                if self.conn.execute("SELECT 1 FROM files WHERE job=? AND epoch=? AND key=?", (job["id"], job["epoch"], path_key(target))).fetchone():
                    raise ValueError("That destination is already present in the inventory.")
                if self.conn.execute("SELECT 1 FROM dirs WHERE job=? AND epoch=? AND path=? COLLATE NOCASE", (job["id"], job["epoch"], str(target))).fetchone():
                    raise ValueError("A folder already occupies that destination.")
            except (OSError, ValueError) as error:
                record["name"].update(state="blocked", blocker=str(error), executable=False)
        if not thumbnails:
            ocr.pop("lines", None)
        return record | {"id": row["id"], "path": str(path), "scope": row["scope"], "filename": path.name, "ocr": ocr,
                         "observed_name": observe_filename(path.name), "metadata": metadata,
                         "naming_profile": ({"state": "validated", "executable": bool(record["name"].get("executable")),
                                             "project": profile["project"], "rule_source": naming_rule["source"] if naming_rule else None}
                                            if profile else {"state": "unvalidated", "executable": False, "reason": NAMING_HOLD}),
                         "size": row["size"], "modified_ns": row["modified"], "can_propose": proposals,
                         "digest": row["digest"], "memberships": memberships, "series": row["series"],
                         "thumbnail": features["thumbnail"] if thumbnails else ""}

    def images(self, job_id, offset, series="", query="", *, thumbnails=True, asset_ids=None):
        job = self.job(job_id)
        visible = self._visible(job)
        selection = ''
        selected = ()
        if asset_ids is not None:
            selected = tuple(asset_ids)
            if not selected:
                return {'items': [], 'more': False}
            if len(selected)>100000 or any(type(value) is not int for value in selected):
                raise ValueError('Choose assets in the current inspection.')
            selection = f' AND f.id IN ({_markers(selected)})'
        args = (job_id, job["epoch"], *visible, series, series, query[:200], query[:200], *selected, PAGE + 1, offset)
        rows = self.conn.execute(f"""SELECT f.*,o.features,o.ocr,o.ocr_key,a.propose FROM files f
            JOIN observations o ON o.job=f.job AND o.scope=f.scope AND o.digest=f.digest
            JOIN scope_access a ON a.job=f.job AND a.path=f.scope
            WHERE f.job=? AND f.epoch=? AND f.scope IN ({_markers(visible)}) AND f.status='analyzed' AND (?='' OR f.series=?)
            AND (instr(lower(f.path),lower(?))>0 OR EXISTS(
                SELECT 1 FROM json_each(o.ocr,'$.lines') WHERE instr(lower(json_extract(value,'$.text')),lower(?))>0))
            {selection} ORDER BY f.id LIMIT ? OFFSET ?""", args).fetchall()
        scope_reviews, images = {}, []
        profile = self.project_registry.profile(job_id)
        for row in rows[:PAGE]:
            try:
                if row["scope"] not in scope_reviews:
                    scope_reviews[row["scope"]] = self._reviews(job, row["scope"])
                reviews, evidence = scope_reviews[row["scope"]]
                images.append(self._image_view(job, row, reviews, evidence, thumbnails=thumbnails, proposals=bool(row["propose"]),
                                               profile=profile if row["scope"] == job["root"] else None))
            except ProtectedPath:
                continue
        return {"items": images, "more": len(rows) > PAGE}

    def naming_binding(self, job_id, asset, source, target):
        profile = self.project_registry.profile(job_id)
        if not profile:
            raise ValueError(NAMING_HOLD)
        job = self.job(job_id)
        items = self.images(job_id, 0, asset_ids=[asset], thumbnails=False)["items"]
        if not items or items[0]["path"] != str(source) or items[0]["scope"] != job["root"]:
            raise ValueError("Choose a current image in the profile's original scope.")
        image = items[0]
        name = image["name"]
        if name["state"] != "proposed":
            raise ValueError(name.get("blocker") or name["reason"])
        if str(Path(job["root"]) / name["destination"]) != str(target):
            raise ValueError("Only the exact destination from the validated naming preview can be reviewed.")
        return {"asset": asset, "epoch": job["epoch"], "profile_revision": profile["revision"], "digest": image["digest"],
                "creation_date": image["metadata"]["date"]}

    def groups(self, job_id, offset):
        job = self.job(job_id)
        visible = self._visible(job)
        rows = self.conn.execute(f"""SELECT series,count(*) AS members FROM files
            WHERE job=? AND epoch=? AND scope IN ({_markers(visible)}) AND status='analyzed' GROUP BY series HAVING count(*)>1
            ORDER BY members DESC,series LIMIT ? OFFSET ?""", (job_id, job["epoch"], *visible, PAGE + 1, offset)).fetchall()
        return {"items": [dict(row) for row in rows[:PAGE]], "more": len(rows) > PAGE}

    def review(self, job_id, asset_id, action, label="", purpose=""):
        if action not in ("confirm", "reject", "purpose"):
            raise ValueError("Choose confirm, reject, or record a purpose.")
        label, purpose = label.strip(), purpose.strip()
        if action != "purpose":
            component(label)
            token = resolve_token(self.registry, label)
            if token:
                label = token[1]["display_name"]
        if purpose or action == "purpose":
            component(purpose)
        self.policy.refresh()
        job = self.job(job_id)
        row = self.conn.execute("SELECT * FROM files WHERE id=? AND job=? AND epoch=? AND status='analyzed'", (asset_id, job_id, job["epoch"])).fetchone()
        if row is None:
            raise ValueError("Choose a current analyzed image.")
        self._validate_scope(job, row["scope"])
        path = self.policy.check_image(Path(row["path"]), retain=self.retains, learn=True)
        if sha256(image_bytes(path)).hexdigest() != row["digest"]:
            raise ValueError("The image changed. Refresh its folder before reviewing it.")
        (identities, _), _ = self._reviews(job, row["scope"])
        if action == "confirm" and any(event["action"] == "confirm" and key != label.casefold()
                                       for key, event in identities.get(row["digest"], {}).items()):
            raise ValueError("This image already has a confirmed identity. Explicitly reject that identity before replacing it.")
        if self.conn.execute("SELECT count(*) FROM reviews WHERE job=?", (job_id,)).fetchone()[0] >= 400:
            raise ValueError("This review has reached its 400-decision limit.")
        event = {"id": uuid4().hex, "action": action, "path": path.as_posix(), "source_path": str(path), "digest": row["digest"],
                 "scope": row["scope"], "label": label, "purpose": purpose, "authority": "local operator"}
        with self.conn:
            self.conn.execute("INSERT INTO reviews(job,event) VALUES(?,?)", (job_id, json.dumps(event)))
        return {"saved": True}

    def rule(self, job_id, project, filename, folder):
        self.policy.refresh()
        job = self.job(job_id)
        if not self._validate_scope(job, job["root"]):
            raise ProtectedPath("Allow name and plan suggestions for the selected scope first.")
        rule = validate_rule(project, filename, folder)
        with self.conn:
            self.conn.execute("UPDATE jobs SET rule=? WHERE id=?", (json.dumps(rule), job_id))
        return rule

    def search(self, job_id, query):
        job = self.job(job_id)
        visible = self._visible(job)
        rows = self.conn.execute(f"""SELECT f.path,f.status,f.scope,o.ocr FROM files f
            LEFT JOIN observations o ON o.job=f.job AND o.scope=f.scope AND o.digest=f.digest
            WHERE f.job=? AND f.epoch=? AND f.scope IN ({_markers(visible)})
            AND (instr(lower(f.path),lower(?))>0 OR EXISTS(
                SELECT 1 FROM json_each(o.ocr,'$.lines') WHERE instr(lower(json_extract(value,'$.text')),lower(?))>0))
            ORDER BY f.path LIMIT 50""", (job_id, job["epoch"], *visible, query, query)).fetchall()
        results = []
        for row in rows:
            try:
                path = self.policy.check(Path(row["path"]))
                match = ""
                if row["ocr"]:
                    self.policy.check_image(path, retain=self.retains)
                    lines = json.loads(row["ocr"]).get("lines", [])
                    match = next((line["text"] for line in lines if query.casefold() in line["text"].casefold()), "")
            except ProtectedPath:
                continue
            results.append({"title": path.name, "group": "INSPECTED FILES", "summary": str(path),
                            "details": f"{path} · {row['status']}" + (f" · Image text: {match}" if match else ""),
                            "touches": ["Current inspection"]})
        return results

    def export(self, job_id):
        self.policy.refresh()
        job = self.job(job_id)
        if not self.retains or not self._validate_scope(job, job["root"]):
            raise ProtectedPath("Saving a plan requires a retained review and permission to propose changes.")
        name = f"Inspection-{job_id}-{uuid4().hex[:8]}.json"
        path = self.data_dir / name
        scopes = [row[0] for row in self.conn.execute("SELECT path FROM scopes WHERE job=?", (job_id,))]
        if any(self.data_dir.is_relative_to(scope) for scope in scopes):
            raise ProtectedPath("Journey's review storage overlaps the inspected source.")
        before = identity(safe_metadata(self.data_dir))
        temporary = None
        try:
            with NamedTemporaryFile(mode="w", dir=self.data_dir, prefix=".inspection-", encoding="utf-8", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write('{"format":"journey-navigator-inspection-1","summary":')
                json.dump(self.summary(job_id), stream)
                for field, load in (("images", lambda offset: self.images(job_id, offset, thumbnails=False)),
                                    ("links", lambda offset: self.links(job_id, offset)),
                                    ("skips", lambda offset: self.issues(job_id, offset))):
                    stream.write(f',"{field}":[\n')
                    offset, separator = 0, ""
                    while True:
                        page = load(offset)
                        for item in page["items"]:
                            stream.write(separator)
                            json.dump(item, stream)
                            separator = ",\n"
                        if not page["more"]:
                            break
                        offset += PAGE
                    stream.write("]")
                stream.write("}\n")
                stream.flush()
                os.fsync(stream.fileno())
            if identity(safe_metadata(self.data_dir)) != before:
                raise ProtectedPath("Journey's review storage changed during export.")
            if os.name == "nt":
                os.rename(temporary, path)
            else:
                os.link(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return {"path": str(path)}
