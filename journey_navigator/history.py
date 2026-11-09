"""Local conversation evidence for a retained inspection, independent of action authority."""

from codecs import getincrementaldecoder
import json
import os
from pathlib import Path
import re
import stat
from uuid import uuid4

from core.file_paths import safe_metadata, signature
from core.project_registry import _claims, _matches, _messages, _source, _texts, _words, asset_name, key_for
from journey_navigator.context import asset_families
from journey_planner.catalog import absolute_path, check_local_drive


FILE_LIMIT = 128
FILE_BYTES = 128 * 1024 * 1024
BUNDLE_BYTES = 768 * 1024 * 1024
RECORD_BYTES = 12 * 1024 * 1024
SLICE_BYTES = 1024 * 1024
CHUNK = 128 * 1024
MAX_MESSAGES = 300_000
MAX_CLAIMS = 80_000
SCHEMA = """
CREATE TABLE IF NOT EXISTS history_sources (
    id TEXT PRIMARY KEY, job TEXT NOT NULL, project TEXT NOT NULL, path TEXT NOT NULL,
    name TEXT NOT NULL, signature TEXT NOT NULL, size INTEGER NOT NULL,
    offset INTEGER NOT NULL DEFAULT 0, phase TEXT NOT NULL DEFAULT 'start',
    status TEXT NOT NULL DEFAULT 'paused', records INTEGER NOT NULL DEFAULT 0,
    messages INTEGER NOT NULL DEFAULT 0, gaps INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT '', finished TEXT
);
CREATE INDEX IF NOT EXISTS history_source_scope ON history_sources(job,project,status);
CREATE TABLE IF NOT EXISTS history_messages (
    source TEXT NOT NULL, message TEXT NOT NULL, PRIMARY KEY(source,message)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS history_claims (
    source TEXT NOT NULL, id TEXT NOT NULL, job TEXT NOT NULL, project TEXT NOT NULL,
    name_key TEXT NOT NULL, match_key TEXT NOT NULL, related_key TEXT NOT NULL,
    kind TEXT NOT NULL, record TEXT NOT NULL, PRIMARY KEY(source,id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS history_match ON history_claims(job,project,match_key,kind);
CREATE INDEX IF NOT EXISTS history_relation ON history_claims(job,project,related_key);
CREATE INDEX IF NOT EXISTS history_kind ON history_claims(job,project,kind);
CREATE TABLE IF NOT EXISTS history_reconciliation (
    job TEXT PRIMARY KEY, project TEXT NOT NULL, epoch INTEGER NOT NULL,
    binding TEXT NOT NULL, summary TEXT NOT NULL, checked TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def name_key(name):
    return Path(name).name.casefold() if name else ""


def search_words(value):
    return re.sub(r"\b(care|touch) (rail|bloom|stone)\b", r"\1\2", _words(value))


def match_key(name):
    """Separate a possible browser-download copy suffix from semantic versions."""
    path = Path(name)
    stem = re.sub(r"\s*\([1-9][0-9]{0,3}\)$", "", path.stem)
    return search_words(stem) + path.suffix.casefold() if path.suffix else ""


def clean(value, limit):
    return "".join(char for char in value[:limit] if char.isprintable()).strip() if isinstance(value, str) else ""


class ExportReader:
    """Read one native conversation object at a time with byte-addressable checkpoints."""

    def __init__(self, stream, offset):
        self.stream, self.offset = stream, offset
        stream.seek(offset)
        if offset == 0 and stream.peek(3)[:3] == b"\xef\xbb\xbf":
            stream.read(3)
            self.offset = 3
        self.decoder = getincrementaldecoder("utf-8")()
        self.json = json.JSONDecoder()
        self.buffer = ""
        self.eof = False

    def fill(self):
        if self.eof:
            return
        data = self.stream.read(CHUNK)
        self.eof = not data
        self.buffer += self.decoder.decode(data, final=self.eof)

    def take(self, count):
        self.offset += len(self.buffer[:count].encode("utf-8"))
        self.buffer = self.buffer[count:]

    def peek(self):
        while True:
            stripped = self.buffer.lstrip(" \t\r\n")
            self.take(len(self.buffer) - len(stripped))
            if self.buffer or self.eof:
                return self.buffer[:1]
            self.fill()

    def record(self):
        if self.peek() != "{":
            raise ValueError("An export entry is not a conversation object.")
        while True:
            try:
                record, end = self.json.raw_decode(self.buffer)
            except json.JSONDecodeError:
                if self.eof:
                    raise ValueError("The conversation export is incomplete or malformed.") from None
                if self.stream.tell() - self.offset > RECORD_BYTES:
                    raise ValueError("A conversation exceeds the 12 MiB record budget or is malformed.") from None
                self.fill()
                continue
            if len(self.buffer[:end].encode("utf-8")) > RECORD_BYTES:
                raise ValueError("A conversation exceeds the 12 MiB record budget.")
            self.take(end)
            if not isinstance(record.get("mapping"), dict) and not isinstance(record.get("messages"), list):
                raise ValueError("Choose ChatGPT conversation JSON with a message tree or a normalized message list.")
            return record

    def finish(self):
        if self.peek():
            raise ValueError("Unexpected data follows the conversation export.")

    def records(self, phase, start):
        if phase == "start":
            char = self.peek()
            if char == "{":
                yield self.record(), "single"
                self.finish()
                return
            if char != "[":
                raise ValueError("The selected file is not a conversation JSON export.")
            self.take(1)
            phase = "first"
        if phase == "single":
            self.finish()
            return
        for index in range(8):
            char = self.peek()
            if char == "]":
                self.take(1)
                self.finish()
                return
            if phase == "next":
                if char != ",":
                    raise ValueError("The conversation export has an invalid entry separator.")
                self.take(1)
            yield self.record(), "next"
            phase = "next"
            if self.offset - start >= SLICE_BYTES or index == 7:
                return


def attachment_record(item, *, part=False):
    if not isinstance(item, dict):
        return None
    if part and item.get("content_type") not in ("image_asset_pointer", "file_asset_pointer"):
        return None
    name = asset_name(item.get("name") or item.get("file_name"))
    pointer = clean(item.get("asset_pointer") or item.get("id") or item.get("file_id"), 180)
    if not name and (not pointer or not part and not str(item.get("mime_type", "")).startswith("image/")):
        return None
    # These are opaque export identifiers. They are never passed to a filesystem or client.
    pointer = pointer if re.fullmatch(r"(?:sediment://|asset://)?[\w.:-]+", pointer) else ""
    dimensions = {key: item[key] for key in ("width", "height")
                  if type(item.get(key)) is int and 0 < item[key] <= 100_000}
    library = clean(item.get("library_file_id"), 100)
    library = library if re.fullmatch(r"libfile_[0-9a-f]+", library) else ""
    return name, {"pointer": pointer, "library_reference": library, "dimensions": dimensions, "bytes": "unavailable"}


def entity_claims(line, project, source):
    if project != "carebloomos" or source["role"] != "user":
        return
    if re.search(r"\b(?:musicstone\b.{0,65}\b(?:beat and melody|melody and beat)|(?:beat and melody|melody and beat)\b.{0,45}\bmusicstone)\b", line, re.I):
        for member in ("Beat", "Melody"):
            yield {"kind": "entity", "name": member, "value": {"entity": "Musicstone", "relation": "duo member"}, "source": source}
    if re.search(r"\b(?:corestone is opalstone|opalstone acts as (?:the )?corestone)\b", line, re.I):
        yield {"kind": "entity", "name": "Opalstone", "value": {"entity": "Corestone", "relation": "identity and current project role"}, "source": source}


def extract(record, archive, signals, project):
    """Yield a message hash and only the structured observations worth retaining."""
    if record.get("is_do_not_remember") is True:
        return
    title = clean(record.get("title"), 160)
    in_title = _matches(signals, title)
    for conversation, message, locator in _messages(record):
        if not isinstance(message, dict):
            continue
        try:
            source = _source(archive, conversation, message, locator)
        except ValueError:
            continue
        if source is None:
            continue
        source.update(title=title, branch=clean(locator, 140))
        native_id = message.get("id")
        message_key = key_for([source["role"], native_id] if isinstance(native_id, str) and native_id else
                              [source["role"], source["conversation"], source["message"]])
        texts = [text[:30_000] for text in _texts(message)]
        in_project = in_title or any(_matches(signals, text) for text in texts)
        claims = []
        for text in texts:
            for line in text.splitlines():
                claims.extend(entity_claims(line, project, source))
                if "." not in line:
                    continue
                for claim in _claims(line, signals, in_project, source):
                    if claim["kind"] == "reference":
                        families = asset_families(Path(claim["name"]).stem)
                        # A same-sentence identification can add context to an opaque filename.
                        if not families and re.search(r"\b(?:is|was|shows|depicts|serves as)\b", line, re.I) and not re.search(
                                r"\b(?:not|never|maybe|could|if|versus|example)\b|[?]", line, re.I):
                            families = asset_families(line)
                        if len(families) == 1:
                            claim["family"] = families[0]
                    claims.append(claim)
        metadata = message.get("metadata")
        content = message.get("content")
        parts = content.get("parts") if isinstance(content, dict) else None
        attachments = metadata.get("attachments") if isinstance(metadata, dict) else None
        candidates = [attachment_record(item) for item in attachments[:64]] if isinstance(attachments, list) else []
        if isinstance(parts, list):
            candidates.extend(attachment_record(item, part=True) for item in parts[:128])
        for attachment in candidates:
            if attachment is None:
                continue
            name, value = attachment
            if in_project or (name and _matches(signals, name)):
                claims.append({"kind": "attachment", "name": name, "value": value, "source": source})
        yield message_key, claims[:128]


class ArchiveHistory:
    def __init__(self, app):
        self.app, self.conn = app, app.conn
        self.conn.executescript(SCHEMA)
        self.conn.create_function("history_match_key", 1, match_key, deterministic=True)
        self.tickets = {}
        self.coverage_cache = {}
        with self.conn:
            self.conn.execute("UPDATE history_sources SET status='paused' WHERE status='queued'")

    @staticmethod
    def project(profile):
        return profile["project"].casefold()

    def context(self, job):
        row = self.app.project_registry._root(job)
        profile = self.app.project_registry.profile(job)
        if not profile:
            raise ValueError("Activate a project profile before importing reference history.")
        return row, profile

    def _file(self, path):
        check_local_drive(path)
        info = safe_metadata(path, read_guard=self.app.project_registry._archive_access)
        if path.suffix.casefold() != ".json" or not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= FILE_BYTES:
            raise ValueError("Choose regular local JSON files up to 128 MiB each.")
        return info

    def preview(self, job, selected):
        _, profile = self.context(job)
        path = absolute_path(selected)
        check_local_drive(path)
        info = safe_metadata(path, read_guard=self.app.project_registry._archive_access)
        skipped = 0
        if stat.S_ISDIR(info.st_mode):
            paths = []
            with os.scandir(path) as entries:
                for index, entry in enumerate(entries):
                    if index >= 4000:
                        raise ValueError("Choose a smaller export folder or an explicit manifest.")
                    if re.fullmatch(r"conversations(?:[-_ (][^/\\]*)?\.json", entry.name, re.I):
                        paths.append(Path(entry.path))
                        if len(paths) > FILE_LIMIT:
                            raise ValueError("Choose at most 128 export files per inspection.")
                    else:
                        skipped += 1
        elif path.name.casefold().endswith(".manifest.json"):
            info = self._file(path)
            if info.st_size > CHUNK:
                raise ValueError("The archive manifest exceeds 128 KiB.")
            with path.open("rb") as stream:
                if signature(os.fstat(stream.fileno())) != signature(info):
                    raise ValueError("The selected manifest changed before reading.")
                data = stream.read(CHUNK + 1)
            if len(data) != info.st_size or signature(self._file(path)) != signature(info):
                raise ValueError("The selected manifest changed while reading.")
            value = json.loads(data.decode("utf-8-sig"))
            files = value.get("files") if isinstance(value, dict) and value.get("format") == "journey-history-manifest-1" else None
            if not isinstance(files, list) or not 1 <= len(files) <= FILE_LIMIT or any(
                    not isinstance(name, str) or not re.fullmatch(r"[^\\/:\x00-\x1f]{1,180}\.json", name, re.I)
                    or name.endswith((" ", ".")) for name in files):
                raise ValueError("The manifest needs 1–128 JSON filenames in its own folder.")
            paths = [path.parent / name for name in files]
        else:
            paths = [path]
        rows = []
        for file in sorted(set(paths), key=lambda item: str(item).casefold()):
            info = self._file(file)
            rows.append({"path": str(file), "name": file.name, "size": info.st_size, "signature": list(signature(info))})
        total = sum(row["size"] for row in rows)
        if not rows or len(rows) > FILE_LIMIT or total > BUNDLE_BYTES:
            raise ValueError("Choose 1–128 supported exports with a combined size up to 768 MiB.")
        ticket = uuid4().hex
        if len(self.tickets) >= 8:
            self.tickets.pop(next(iter(self.tickets)))
        self.tickets[ticket] = (job, self.project(profile), rows)
        return {"ticket": ticket, "project": profile["project"], "files": rows, "bytes": total, "other_entries": skipped}

    def enqueue(self, job, ticket):
        _, profile = self.context(job)
        key = self.project(profile)
        draft = self.tickets.pop(ticket, None)
        if not draft or draft[:2] != (job, key):
            raise ValueError("Preview the authorized local archive selection again.")
        saved = {(row["path"], row["signature"]): row for row in self.conn.execute(
            "SELECT id,path,signature,status,size FROM history_sources WHERE job=? AND project=?", (job, key))}
        pending = []
        for row in draft[2]:
            path = Path(row["path"])
            info = self._file(path)
            if list(signature(info)) != row["signature"] or info.st_size != row["size"]:
                raise ValueError("An export changed since preview. Review the source selection again.")
            encoded = json.dumps(row["signature"])
            if (row["path"], encoded) not in saved:
                pending.append(row)
        if len(saved) + len(pending) > FILE_LIMIT or sum(row["size"] for row in saved.values()) + sum(
                row["size"] for row in pending) > BUNDLE_BYTES:
            raise ValueError("This scope reached its retained archive budget. Forget old imports before adding more.")
        with self.conn:
            for row in draft[2]:
                prior = saved.get((row["path"], json.dumps(row["signature"])))
                if prior and prior["status"] == "paused":
                    self.conn.execute("UPDATE history_sources SET status='queued' WHERE id=?", (prior["id"],))
            self.conn.executemany("""INSERT INTO history_sources(id,job,project,path,name,signature,size,status)
                VALUES(?,?,?,?,?,?,?,'queued')""",
                ((uuid4().hex, job, key, row["path"], row["name"], json.dumps(row["signature"]), row["size"]) for row in pending))
        return self.status(job)

    def pause(self, job=None):
        self.conn.execute("UPDATE history_sources SET status='paused' WHERE status='queued' AND (? IS NULL OR job=?)", (job, job))

    def forget(self, job):
        self.tickets = {ticket: draft for ticket, draft in self.tickets.items() if draft[0] != job}
        self.conn.execute("DELETE FROM history_messages WHERE source IN (SELECT id FROM history_sources WHERE job=?)", (job,))
        self.conn.execute("DELETE FROM history_claims WHERE job=?", (job,))
        self.conn.execute("DELETE FROM history_sources WHERE job=?", (job,))
        self.conn.execute("DELETE FROM history_reconciliation WHERE job=?", (job,))
        self.coverage_cache.pop(job, None)
        if self.conn.execute("SELECT 1 FROM sqlite_schema WHERE type='table' AND name='patrol_tasks'").fetchone():
            destinations = "SELECT id FROM destinations WHERE job=?"
            self.conn.execute(f"UPDATE patrol_tasks SET status='pending',cursor=0 WHERE kind IN ('assess','reconcile') AND destination IN ({destinations})", (job,))
            for table in ("patrol_assets", "patrol_questions", "virtual_memberships", "virtual_collections"):
                self.conn.execute(f"DELETE FROM {table} WHERE destination IN ({destinations})", (job,))

    def binding(self, job):
        profile = self.app.project_registry.profile(job)
        if not profile:
            return ""
        values = [row[0] for row in self.conn.execute(
            "SELECT id FROM history_sources WHERE job=? AND project=? AND status='complete' ORDER BY id", (job, self.project(profile)))]
        return key_for(values) if values else ""

    def advance(self):
        source = self.conn.execute("SELECT * FROM history_sources WHERE status='queued' ORDER BY rowid LIMIT 1").fetchone()
        if source is None:
            return False
        try:
            _, profile = self.context(source["job"])
            if self.project(profile) != source["project"]:
                raise PermissionError("The project profile changed. Review the reference scope before resuming.")
            audit = self.app.project_audit.document(source["job"])
            subjects = audit["subjects"] if audit and audit["project"].casefold() == source["project"] else []
            terms = tuple(filter(None, map(_words, [profile["project"], *profile["signals"], *subjects])))
            self._advance(source, terms)
        except PermissionError:
            with self.conn:
                self.pause(source["job"])
        except (ValueError, OSError, OverflowError, RecursionError):
            with self.conn:
                self.conn.execute("DELETE FROM history_claims WHERE source=?", (source["id"],))
                self.conn.execute("DELETE FROM history_messages WHERE source=?", (source["id"],))
                self.conn.execute("""UPDATE history_sources SET status='failed',
                    error='Export changed, is unreadable, exceeds a budget or contains unsupported JSON.' WHERE id=?""", (source["id"],))
        return True

    def _advance(self, source, terms):
        path = Path(source["path"])
        expected = json.loads(source["signature"])
        def unchanged(info):
            return list(signature(info)) == expected and info.st_size == source["size"]
        if not unchanged(self._file(path)):
            raise ValueError("Export changed before reading.")
        messages, claims = set(), {}
        phase, records, count, gaps = source["phase"], 0, 0, 0
        complete = True
        with path.open("rb") as stream:
            if not unchanged(os.fstat(stream.fileno())):
                raise ValueError("Export changed during open.")
            reader = ExportReader(stream, source["offset"])
            for record, phase in reader.records(phase, source["offset"]):
                records += 1
                if record.get("is_do_not_remember") is True:
                    gaps += 1
                for message_key, observed in extract(record, source["name"], terms, source["project"]):
                    count += 1
                    messages.add(message_key)
                    for claim in observed:
                        identifier = key_for([message_key, claim["kind"], claim["name"], claim["value"], claim.get("family")])
                        claims.setdefault(identifier, claim)
                        if len(claims) > 4000 or count > 18_000:
                            raise ValueError("Conversation evidence exceeds the per-checkpoint budget.")
            complete = reader.eof and not reader.buffer
            offset = reader.offset
        if not unchanged(self._file(path)):
            raise ValueError("Export changed while reading.")
        with self.conn:
            self.conn.executemany("INSERT OR IGNORE INTO history_messages VALUES(?,?)", ((source["id"], item) for item in messages))
            self.conn.executemany("INSERT OR IGNORE INTO history_claims VALUES(?,?,?,?,?,?,?,?,?)",
                ((source["id"], identifier, source["job"], source["project"], name_key(claim["name"]), match_key(claim["name"]),
                  name_key(claim["value"]["asset"]) if claim["kind"] == "relationship" else "", claim["kind"], json.dumps(claim))
                 for identifier, claim in claims.items()))
            counters = self.conn.execute("SELECT sum(messages) FROM history_sources WHERE job=? AND project=? AND status<>'failed'",
                                         (source["job"], source["project"])).fetchone()[0] or 0
            if counters + count > MAX_MESSAGES or self.conn.execute(
                "SELECT count(*) FROM history_claims WHERE job=? AND project=?", (source["job"], source["project"])).fetchone()[0] > MAX_CLAIMS:
                raise ValueError("This inspection reached its retained archive limit.")
            self.conn.execute("""UPDATE history_sources SET offset=?,phase=?,records=records+?,messages=messages+?,gaps=gaps+?,
                status=?,finished=CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END WHERE id=?""",
                (offset, phase, records, count, gaps, "complete" if complete else "queued", complete, source["id"]))
            if complete:
                self.app.project_registry._changed(source["job"])

    def evidence(self, job, profile, name):
        if not profile:
            return []
        rows = self.conn.execute("""SELECT c.record FROM history_claims c JOIN history_sources s ON s.id=c.source
            WHERE c.job=? AND c.project=? AND s.status='complete' AND (c.match_key=? OR c.related_key=?)
            GROUP BY c.id ORDER BY c.name_key<>?, c.kind='reference',c.id LIMIT 24""",
            (job, self.project(profile), match_key(name), name_key(name), name_key(name)))
        records = []
        for row in rows:
            record = json.loads(row[0])
            match = ("filename candidate" if name_key(record["name"]) == name_key(name) else
                     "variant candidate" if match_key(record["name"]) == match_key(name) else "related reference")
            records.append(record | {"match": match})
        return records

    def entity_links(self, job, profile, name):
        if not profile:
            return []
        stem = _words(Path(name).stem)
        rows = self.conn.execute("""SELECT c.record FROM history_claims c JOIN history_sources s ON s.id=c.source
            WHERE c.job=? AND c.project=? AND s.status='complete' AND c.kind='entity' GROUP BY c.name_key LIMIT 30""",
            (job, self.project(profile)))
        records = (json.loads(row[0]) for row in rows)
        return [item for item in records if stem == _words(item["name"]) or
                stem.startswith(_words(item["name"]) + " ") and asset_families(stem)]

    def find(self, job, query, limit=18):
        profile = self.app.project_registry.profile(job)
        terms = search_words(query[:200])
        if not profile or not terms:
            return []
        rows = self.conn.execute("""SELECT c.record FROM history_claims c JOIN history_sources s ON s.id=c.source
            WHERE c.job=? AND c.project=? AND s.status='complete' AND c.name_key<>'' AND
            (instr(c.name_key,?)>0 OR instr(c.match_key,?)>0) GROUP BY c.name_key,c.kind
            ORDER BY c.name_key LIMIT ?""", (job, self.project(profile), query[:200].casefold(), terms, limit))
        return [json.loads(row[0]) for row in rows]

    def status(self, job):
        current, profile = self.context(job)
        key = (job, self.project(profile))
        rows = [dict(row) for row in self.conn.execute("""SELECT name,status,size,offset,records,messages,gaps,error,finished
            FROM history_sources WHERE job=? AND project=? ORDER BY rowid""", key)]
        binding = self.binding(job)
        cached = self.coverage_cache.get(job)
        if cached is None or cached[:2] != (key[1], binding):
            unique = self.conn.execute("""SELECT count(DISTINCT m.message) FROM history_messages m JOIN history_sources s ON s.id=m.source
                WHERE s.job=? AND s.project=? AND s.status='complete'""", key).fetchone()[0]
            counts = self.conn.execute("""SELECT count(DISTINCT c.id),count(DISTINCT CASE WHEN c.match_key<>'' THEN c.name_key END),
                count(DISTINCT CASE WHEN c.kind='attachment' THEN c.id END) FROM history_claims c JOIN history_sources s ON s.id=c.source
                WHERE c.job=? AND c.project=? AND s.status='complete'""", key).fetchone()
            self.coverage_cache[job] = (key[1], binding, unique, counts)
        else:
            unique, counts = cached[2:]
        last = self.conn.execute("SELECT * FROM history_reconciliation WHERE job=? AND project=?", key).fetchone()
        reconciliation = None
        if last:
            reconciliation = json.loads(last["summary"]) | {"checked": last["checked"],
                "current": last["binding"] == self.reconciliation_binding(job) and last["epoch"] == current["epoch"]}
        return {"files": rows, "unique_messages": unique, "claims": counts[0], "referenced_assets": counts[1],
                "attachment_records": counts[2], "reconciliation": reconciliation}

    def reconciliation_binding(self, job):
        return key_for([self.binding(job), self.app.project_audit.binding(job)])

    def reconcile(self, job):
        row, profile = self.context(job)
        epoch = row["epoch"]
        # The initial scope owns the active profile. Linked collections remain independent.
        references = self.conn.execute("""SELECT c.match_key,count(DISTINCT c.name_key)
            FROM history_claims c JOIN history_sources s ON s.id=c.source
            WHERE c.job=? AND c.project=? AND s.status='complete' AND c.match_key<>'' GROUP BY c.match_key""",
            (job, self.project(profile))).fetchall()
        inventory, digests = {}, set()
        for item in self.conn.execute("""SELECT path,digest FROM files WHERE job=? AND epoch=? AND scope=? AND status='analyzed'""",
                                     (job, epoch, row["root"])):
            try:
                self.app.policy.check_image(Path(item["path"]), retain=True)
            except PermissionError:
                continue
            inventory.setdefault(match_key(item["path"]), set()).add(item["digest"])
            digests.add(item["digest"])
        matched = sum(count for key, count in references if key in inventory)
        ambiguous = sum(count for key, count in references if len(inventory.get(key, ())) > 1)
        audit = self.app.project_audit.document(job)
        proofs = [item for item in audit["examples"] if item.get("sha256") in digests] if audit and audit["project"].casefold() == self.project(profile) else []
        result = {"name_candidates": matched, "ambiguous_names": ambiguous,
                  "not_located_in_scope": sum(count for _, count in references) - matched,
                  "archive_bytes_verified": 0, "byte_verified_exemplars": len(proofs), "analyzed_names": len(inventory)}
        with self.conn:
            self.conn.execute("""INSERT OR REPLACE INTO history_reconciliation(job,project,epoch,binding,summary)
                VALUES(?,?,?,?,?)""", (job, self.project(profile), epoch, self.reconciliation_binding(job), json.dumps(result)))
        return result
