"""Durable, bounded discovery and review for Navigator's selected folders."""

from hashlib import sha256
import json
import os
from pathlib import Path
import secrets
import sqlite3
import stat
from tempfile import NamedTemporaryFile
from time import monotonic
from uuid import uuid4

from core.file_paths import safe_metadata, signature
from journey_navigator.links import Boundaries, ProtectedPath, identity, kind_of, path_key, resolve_folder
from journey_planner.catalog import File, Plan, absolute_path, check_local_drive, component
from journey_vision.observe import IMAGE_FORMATS, decode_image, describe, image_bytes
from journey_vision.steward import (
    DEFAULT_RULE, SIMILAR, _identity, _purpose, draft_names, pixel_distance, review_index, validate_rule,
)


ENTRY_BATCH = 256
IMAGE_BATCH = 12
PAGE = 24
SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY, root TEXT NOT NULL, physical_id TEXT NOT NULL, epoch INTEGER NOT NULL,
    rule TEXT NOT NULL, updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS scopes (
    job TEXT NOT NULL, path TEXT NOT NULL, resolution TEXT NOT NULL, grants TEXT NOT NULL, PRIMARY KEY(job,path)
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
CREATE TABLE IF NOT EXISTS cache (
    job TEXT NOT NULL, digest TEXT NOT NULL, features TEXT NOT NULL, bucket TEXT NOT NULL,
    representative INTEGER NOT NULL DEFAULT 0, series TEXT NOT NULL, PRIMARY KEY(job,digest)
);
CREATE TABLE IF NOT EXISTS links (
    id INTEGER PRIMARY KEY, job TEXT NOT NULL, key TEXT NOT NULL, path TEXT NOT NULL, kind TEXT NOT NULL,
    scope TEXT NOT NULL, epoch INTEGER NOT NULL, record TEXT NOT NULL, UNIQUE(job,key)
);
CREATE TABLE IF NOT EXISTS gaps (
    job TEXT NOT NULL, path TEXT NOT NULL, epoch INTEGER NOT NULL, reason TEXT NOT NULL, PRIMARY KEY(job,path)
);
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY, job TEXT NOT NULL, event TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS directory_queue ON dirs(job,epoch,status);
CREATE INDEX IF NOT EXISTS file_queue ON files(job,epoch,status,id);
CREATE INDEX IF NOT EXISTS visual_buckets ON cache(job,bucket,representative);
CREATE INDEX IF NOT EXISTS file_series ON files(job,epoch,series,id);
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


class Workbench:
    def __init__(self, data_dir, *, blocked=(), hold_store=None, perception_store=None):
        self.data_dir = _prepare_data_dir(data_dir)
        self.policy = Boundaries((self.data_dir, *blocked), hold_store=hold_store, perception_store=perception_store)
        self.database = self.data_dir / "navigator-inspection.sqlite"
        for suffix in ("", "-journal", "-wal", "-shm"):
            path = self.database.with_name(self.database.name + suffix)
            if os.path.lexists(path) and not stat.S_ISREG(safe_metadata(path).st_mode):
                raise ValueError("Journey's review storage contains an unexpected file type.")
        self.conn = sqlite3.connect(self.database, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.tickets = {}
        self.cursor = None

    def close(self):
        self.pause()
        self.conn.close()

    def pause(self):
        if self.cursor:
            self.cursor[1].close()
            self.cursor = None

    def jobs(self):
        return [dict(row) for row in self.conn.execute("SELECT id,root,updated FROM jobs ORDER BY updated DESC LIMIT 100")]

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

    def select(self, value, *, job_id=None, link_id=None):
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
        return self._selection(result, allowed, job_id, link_id)

    def approve(self, ticket):
        self.policy.refresh()
        data = self.tickets.pop(ticket, None)
        if not data or data[-1] < monotonic():
            raise ValueError("This link review expired. Select the link again.")
        preview, grants, job_id, link_id, _ = data
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
        return self._selection(result, grants, job_id, link_id)

    def _selection(self, result, grants, job_id, link_id):
        response = result.record()
        if result.status == "approval_required":
            self.tickets = {key: value for key, value in self.tickets.items() if value[-1] >= monotonic()}
            if len(self.tickets) >= 64:
                self.tickets.pop(next(iter(self.tickets)))
            ticket = secrets.token_urlsafe(24)
            self.tickets[ticket] = (result, grants, job_id, link_id, monotonic() + 300)
            response["ticket"] = ticket
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
            existing = self.conn.execute("SELECT root FROM jobs WHERE id=?", (job_id,)).fetchone()
            if existing and Path(existing["root"]) != root:
                # Keep prior review history if the physical directory has been moved.
                job_id = sha256((result.physical_id + path_key(root)).encode()).hexdigest()[:24]
        with self.conn:
            self.conn.execute("INSERT OR IGNORE INTO jobs(id,root,physical_id,epoch,rule) VALUES(?,?,?,1,?)",
                              (job_id, result.target, result.physical_id, json.dumps(DEFAULT_RULE)))
            job = self.job(job_id)
            self.conn.execute("UPDATE jobs SET updated=CURRENT_TIMESTAMP WHERE id=?", (job_id,))
            self.conn.execute(f"INSERT OR {'REPLACE' if direct_selection else 'IGNORE'} INTO scopes VALUES(?,?,?,?)",
                              (job_id, result.target, json.dumps(result.record()), json.dumps(grants)))
            added = self._queue_dir(job, result.physical_id, result.target, result.target)
            if result.hops:
                row = self.conn.execute("SELECT scope FROM links WHERE job=? AND id=?", (job_id, link_id)).fetchone()
                origin_scope = row["scope"] if row else result.target
                if not added:
                    result.status = "already_covered"
                    result.reason = "This physical folder already has a discovery record."
                self._record_link(job, result.selected, result.hops[0]["kind"], origin_scope, result)
        return response | {"job": job_id}

    def _queue_dir(self, job, physical_id, path, scope):
        return self.conn.execute("""INSERT INTO dirs VALUES(?,?,?,?,?,'pending')
            ON CONFLICT(job,physical_id) DO UPDATE SET path=excluded.path,scope=excluded.scope,epoch=excluded.epoch,status='pending'
            WHERE dirs.epoch<>excluded.epoch""", (job["id"], physical_id, path, scope, job["epoch"])).rowcount != 0

    def _validate_scope(self, job, scope):
        row = self.conn.execute("SELECT resolution,grants FROM scopes WHERE job=? AND path=?", (job["id"], scope)).fetchone()
        if row is None:
            raise ProtectedPath("The folder has no recorded read-only scope.")
        prior = json.loads(row["resolution"])
        result = resolve_folder(Path(prior["selected"]), self.policy, json.loads(row["grants"]))
        if result.record() != prior:
            raise ProtectedPath("The saved source or link changed. Select it again to verify the destination.")

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

    def _gap(self, job, path, reason):
        self.conn.execute("INSERT OR REPLACE INTO gaps VALUES(?,?,?,?)", (job["id"], str(path), job["epoch"], reason))

    def _discover_entry(self, job, scope, entry):
        path = Path(entry.path)
        try:
            self.policy.check(path)
            info = entry.stat(follow_symlinks=False)
            kind = kind_of(path, info)
            if kind == "folder":
                self._queue_dir(job, identity(path.lstat()), str(path), scope)
            elif kind != "file":
                prior = self.conn.execute("SELECT * FROM scopes WHERE job=? AND json_extract(resolution,'$.selected')=?",
                                          (job["id"], str(path))).fetchone()
                result = resolve_folder(path, self.policy, (job["root"], scope))
                if prior and result.status == "approval_required":
                    candidate = resolve_folder(path, self.policy, json.loads(prior["grants"]))
                    if candidate.record() == json.loads(prior["resolution"]):
                        result = candidate
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
                self._gap(job, path, "This is a special filesystem entry.")
        except (OSError, ValueError) as error:
            self._gap(job, path, _message(error))

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
            for _ in range(ENTRY_BATCH):
                entry = next(self.cursor[1], None)
                if entry is None:
                    self.pause()
                    self.conn.execute("UPDATE dirs SET status='done' WHERE job=? AND physical_id=?", (job["id"], row["physical_id"]))
                    break
                self._discover_entry(job, row["scope"], entry)
            if signature(safe_metadata(path, read_guard=self.policy.check)) != signature(before):
                self.pause()
                self.conn.execute("UPDATE dirs SET status='pending' WHERE job=? AND physical_id=?", (job["id"], row["physical_id"]))
        except (OSError, ValueError) as error:
            self.pause()
            self._gap(job, path, _message(error))
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
            self.policy.check_image(path)
            if not path.is_relative_to(row["scope"]):
                raise ProtectedPath("The image is outside the verified folder.")
            data = image_bytes(path, File(row["size"], row["modified"], path.name))
            digest = sha256(data).hexdigest()
            cached = self.conn.execute("SELECT features,series FROM cache WHERE job=? AND digest=?", (job["id"], digest)).fetchone()
            fmt = IMAGE_FORMATS[path.suffix.casefold()]
            if cached:
                if json.loads(cached["features"])["format"] != fmt:
                    raise ValueError("This image's contents and filename extension disagree.")
                series = cached["series"]
            else:
                features = describe(decode_image(data, fmt)) | {"format": fmt}
                ratio = features["width"] / features["height"]
                bucket = f"{round(min(ratio, 3) * 4)}:{int(features['transparency'] >= .23)}"
                candidates = self.conn.execute("""SELECT digest,features FROM cache WHERE job=? AND bucket=? AND representative=1
                    ORDER BY digest LIMIT 32""", (job["id"], bucket)).fetchall()
                score, series = min(((pixel_distance(features, json.loads(example["features"])), example["digest"])
                                     for example in candidates), default=(1, digest))
                if score > SIMILAR:
                    series = digest
                self.conn.execute("INSERT INTO cache VALUES(?,?,?,?,?,?)", (job["id"], digest, json.dumps(features), bucket, series == digest, series))
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
                                     (job_id, job["epoch"], IMAGE_BATCH)).fetchall()
            for row in rows:
                self._analyze(job, row, checked)
        return self.summary(job_id)

    def summary(self, job_id):
        job = self.job(job_id)
        params = (job_id, job["epoch"])
        counts = dict(self.conn.execute("SELECT status,count(*) FROM files WHERE job=? AND epoch=? GROUP BY status", params))
        folders = dict(self.conn.execute("SELECT status,count(*) FROM dirs WHERE job=? AND epoch=? GROUP BY status", params))
        reused, = self.conn.execute("SELECT count(*) FROM files WHERE job=? AND epoch=? AND reused=1", params).fetchone()
        gaps, = self.conn.execute("SELECT count(*) FROM gaps WHERE job=? AND epoch=?", params).fetchone()
        links, attention = self.conn.execute("SELECT count(*),sum(json_extract(record,'$.status') NOT IN ('ready','already_covered')) FROM links WHERE job=? AND epoch=?", params).fetchone()
        return {"id": job_id, "root": job["root"], "files": sum(counts.values()), "folders": sum(folders.values()),
                "analyzed": counts.get("analyzed", 0), "pending": counts.get("pending", 0), "unsupported": counts.get("unsupported", 0),
                "pending_folders": folders.get("pending", 0), "reused": reused, "skipped": gaps + counts.get("skipped", 0),
                "links": links, "link_attention": attention or 0, "rule": json.loads(job["rule"])}

    def links(self, job_id, offset):
        job = self.job(job_id)
        rows = self.conn.execute("SELECT * FROM links WHERE job=? AND epoch=? ORDER BY id LIMIT ? OFFSET ?", (job_id, job["epoch"], PAGE + 1, offset)).fetchall()
        return {"items": [json.loads(row["record"]) | {"id": row["id"], "kind": row["kind"]} for row in rows[:PAGE]],
                "more": len(rows) > PAGE}

    def issues(self, job_id, offset):
        job = self.job(job_id)
        key = (job_id, job["epoch"])
        rows = self.conn.execute("""SELECT path,reason FROM gaps WHERE job=? AND epoch=?
            UNION ALL SELECT path,reason FROM files WHERE job=? AND epoch=? AND status='skipped'
            ORDER BY path LIMIT ? OFFSET ?""", (*key, *key, PAGE + 1, offset)).fetchall()
        return {"items": [dict(row) for row in rows[:PAGE]], "more": len(rows) > PAGE}

    def _reviews(self, job):
        events = [json.loads(row[0]) for row in self.conn.execute("SELECT event FROM reviews WHERE job=? ORDER BY id", (job["id"],))]
        cache = {}
        allowed, checked = [], set()
        for event in events:
            try:
                self._check_scope(job, event["scope"], checked)
                self.policy.check_image(Path(event["source_path"]))
            except ProtectedPath:
                continue
            allowed.append(event)
            if event["digest"] in cache:
                continue
            row = self.conn.execute("SELECT features FROM cache WHERE job=? AND digest=?", (job["id"], event["digest"])).fetchone()
            if row:
                cache[event["digest"]] = {"features": json.loads(row["features"])}
        return review_index([event for event in allowed if event["digest"] in cache]), cache

    def _image_view(self, job, row, reviews, evidence, *, thumbnails):
        path = self.policy.check_image(Path(row["path"]))
        features = json.loads(row["features"])
        asset = {"digest": row["digest"], "features": features}
        identities, purposes = reviews
        record = {"identity": _identity(asset, identities, evidence),
                  "purpose": _purpose(path.as_posix(), asset, purposes, evidence)}
        memberships = [f"Visual series {row['series'][:8]}"]
        if record["purpose"]["label"]:
            memberships.append(record["purpose"]["label"])
        if record["identity"]["label"]:
            memberships.append(f"{record['identity']['state'].replace('_', ' ')} · {record['identity']['label']}")
        relative = path.relative_to(row["scope"]).as_posix()
        draft = Plan(row["scope"], "", files={relative: File(row["size"], row["modified"], path.name)})
        draft_names(draft, {relative: record}, json.loads(job["rule"]))
        if record["name"]["state"] == "proposed":
            target = Path(row["scope"]) / record["name"]["destination"]
            try:
                self.policy.check(target)
                if self.conn.execute("SELECT 1 FROM files WHERE job=? AND epoch=? AND key=?", (job["id"], job["epoch"], path_key(target))).fetchone():
                    raise ValueError("That destination is already present in the inventory.")
                if self.conn.execute("SELECT 1 FROM dirs WHERE job=? AND epoch=? AND path=? COLLATE NOCASE", (job["id"], job["epoch"], str(target))).fetchone():
                    raise ValueError("A folder already occupies that destination.")
            except (OSError, ValueError) as error:
                record["name"].update(state="blocked", blocker=str(error))
        return record | {"id": row["id"], "path": str(path), "scope": row["scope"], "filename": path.name,
                         "digest": row["digest"], "memberships": memberships, "series": row["series"],
                         "thumbnail": features["thumbnail"] if thumbnails else ""}

    def images(self, job_id, offset, series="", query="", *, thumbnails=True):
        self.policy.refresh()
        job = self.job(job_id)
        self._validate_scope(job, job["root"])
        args = (job_id, job["epoch"], series, series, query[:200], PAGE + 1, offset)
        rows = self.conn.execute("""SELECT f.*,c.features FROM files f JOIN cache c ON c.job=f.job AND c.digest=f.digest
            WHERE f.job=? AND f.epoch=? AND f.status='analyzed' AND (?='' OR f.series=?) AND instr(lower(f.path),lower(?))>0
            ORDER BY f.id LIMIT ? OFFSET ?""", args).fetchall()
        reviews, evidence = self._reviews(job)
        checked, images = {job["root"]}, []
        for row in rows[:PAGE]:
            try:
                self._check_scope(job, row["scope"], checked)
                images.append(self._image_view(job, row, reviews, evidence, thumbnails=thumbnails))
            except ProtectedPath:
                continue
        return {"items": images, "more": len(rows) > PAGE}

    def groups(self, job_id, offset):
        job = self.job(job_id)
        rows = self.conn.execute("""SELECT series,count(*) AS members FROM files
            WHERE job=? AND epoch=? AND status='analyzed' GROUP BY series HAVING count(*)>1
            ORDER BY members DESC,series LIMIT ? OFFSET ?""", (job_id, job["epoch"], PAGE + 1, offset)).fetchall()
        return {"items": [dict(row) for row in rows[:PAGE]], "more": len(rows) > PAGE}

    def review(self, job_id, asset_id, action, label="", purpose=""):
        if action not in ("confirm", "reject", "purpose"):
            raise ValueError("Choose confirm, reject, or record a purpose.")
        label, purpose = label.strip(), purpose.strip()
        if action != "purpose":
            component(label)
        if purpose or action == "purpose":
            component(purpose)
        self.policy.refresh()
        job = self.job(job_id)
        row = self.conn.execute("SELECT * FROM files WHERE id=? AND job=? AND epoch=? AND status='analyzed'", (asset_id, job_id, job["epoch"])).fetchone()
        if row is None:
            raise ValueError("Choose a current analyzed image.")
        self._validate_scope(job, row["scope"])
        path = self.policy.check_image(Path(row["path"]))
        if sha256(image_bytes(path)).hexdigest() != row["digest"]:
            raise ValueError("The image changed. Refresh its folder before reviewing it.")
        (identities, _), _ = self._reviews(job)
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
        self.job(job_id)
        rule = validate_rule(project, filename, folder)
        with self.conn:
            self.conn.execute("UPDATE jobs SET rule=? WHERE id=?", (json.dumps(rule), job_id))
        return rule

    def search(self, job_id, query):
        self.policy.refresh()
        job = self.job(job_id)
        self._validate_scope(job, job["root"])
        rows = self.conn.execute("""SELECT path,status,scope FROM files WHERE job=? AND epoch=? AND instr(lower(path),lower(?))>0
            ORDER BY path LIMIT 50""", (job_id, job["epoch"], query)).fetchall()
        results, checked = [], {job["root"]}
        for row in rows:
            try:
                self._check_scope(job, row["scope"], checked)
                path = self.policy.check(Path(row["path"]))
            except ProtectedPath:
                continue
            results.append({"title": path.name, "group": "INSPECTED FILES", "summary": str(path),
                            "details": f"{path} · {row['status']}", "touches": ["Saved inspection"]})
        return results

    def export(self, job_id):
        self.job(job_id)
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
