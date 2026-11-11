"""Review and atomically activate a local project pack for one inspection."""

from io import BytesIO
import json
import os
from pathlib import Path
import stat
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

from core.file_paths import safe_metadata, signature
from core.naming_audit import FORMAT as AUDIT_FORMAT, validate_audit
from core.project_registry import PATTERN_FORMAT, PROFILE_FORMAT, key_for
from journey_navigator.registry import validate_claim, validate_profile
from journey_planner.catalog import absolute_path, check_local_drive


PACK_FORMAT = "journey-project-pack-1"
MAX_BYTES = 512 * 1024


def pack_documents(data, extension):
    if extension == ".json":
        document = json.loads(data.decode("utf-8-sig"))
        if not isinstance(document, dict) or document.get("format") != PACK_FORMAT:
            raise ValueError("Choose a Journey project pack JSON or evidence ZIP.")
        return [document["profile"], document.get("audit")]
    try:
        with ZipFile(BytesIO(data)) as archive:
            files = archive.infolist()
            if not 1 <= len(files) <= 16 or sum(item.file_size for item in files) > MAX_BYTES:
                raise ValueError("The evidence ZIP exceeds the project pack budget.")
            seen, documents = set(), []
            for item in files:
                name = item.filename
                if (name.casefold() in seen or "/" in name or "\\" in name or not name.casefold().endswith(".json")
                        or item.flag_bits & 1):
                    raise ValueError("The evidence ZIP must contain distinct, unencrypted top-level JSON files.")
                seen.add(name.casefold())
                with archive.open(item) as stream:
                    contents = stream.read(MAX_BYTES + 1)
                    if len(contents) != item.file_size:
                        raise ValueError("A project document exceeded the pack budget.")
                documents.append(json.loads(contents.decode("utf-8-sig")))
            return documents
    except (BadZipFile, NotImplementedError, RuntimeError):
        raise ValueError("The selected evidence ZIP is unreadable or uses unsupported compression.") from None


class ProjectPacks:
    def __init__(self, app):
        self.app, self.conn = app, app.conn
        self.tickets = {}
        self.conn.execute("""CREATE TABLE IF NOT EXISTS project_pack_backup (
            job TEXT PRIMARY KEY, profile TEXT, audit TEXT
        )""")

    def _current(self, job):
        profile = self.app.project_registry.profile(job)
        if profile:
            profile = {key: value for key, value in profile.items() if key not in ("fingerprint", "revision", "knowledge_version")}
        return profile, self.app.project_audit.document(job)

    def preview(self, job, selected):
        self.app.project_registry._root(job)
        path = absolute_path(selected)
        check_local_drive(path)
        access = self.app.project_registry._archive_access
        before = safe_metadata(path, read_guard=access)
        extension = path.suffix.casefold()
        if extension not in (".json", ".zip") or not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_BYTES:
            raise ValueError("Choose one local Journey evidence ZIP or pack JSON up to 512 KiB.")
        with path.open("rb") as stream:
            if signature(os.fstat(stream.fileno())) != signature(before):
                raise ValueError("The pack changed before reading.")
            data = stream.read(MAX_BYTES + 1)
        if len(data) != before.st_size or signature(safe_metadata(path, read_guard=access)) != signature(before):
            raise ValueError("The pack changed while reading.")
        profiles, audits = {}, {}
        for document in pack_documents(data, extension):
            if not isinstance(document, dict):
                continue
            if document.get("format") in (PROFILE_FORMAT, PATTERN_FORMAT):
                profile = validate_profile(document)
                evidence = document.get("evidence", [])
                if not isinstance(evidence, list) or len(evidence) > 100:
                    raise ValueError("The pack includes too many starter records.")
                seed = [validate_claim(claim) for claim in evidence]
                key = profile["project"].casefold()
                if key in profiles:
                    raise ValueError("The pack includes multiple profiles for one project.")
                profiles[key] = profile | {"evidence": seed}
            elif document.get("format") == AUDIT_FORMAT:
                audit = validate_audit(document)
                key = audit["project"].casefold()
                if key in audits:
                    raise ValueError("The pack includes multiple audits for one project.")
                audits[key] = audit
        if not profiles or set(audits) - set(profiles):
            raise ValueError("The pack needs a project profile for each included naming audit.")
        current, active_audit = self._current(job)
        active = current or active_audit
        choices = []
        for key, value in profiles.items():
            compatible = not active or active["project"].casefold() == key
            old = {key_for(rule) for rule in current["rules"]} if current and compatible else set()
            new = {key_for(rule) for rule in value["rules"]}
            choices.append({"key": key, "project": value["project"], "compatible": compatible,
                            "rules": len(new), "rules_added": len(new - old), "rules_removed": len(old - new),
                            "includes_audit": key in audits})
        ticket = uuid4().hex
        if len(self.tickets) >= 8:
            self.tickets.pop(next(iter(self.tickets)))
        self.tickets[ticket] = (job, key_for([current, active_audit]), profiles, audits)
        return {"ticket": ticket, "name": path.name, "choices": choices, "active": active["project"] if active else None}

    def apply(self, job, ticket, project):
        self.app.project_registry._root(job)
        preview = self.tickets.pop(ticket, None)
        current, audit = self._current(job)
        if not preview or preview[:2] != (job, key_for([current, audit])) or project not in preview[2]:
            raise ValueError("Review the pack and the current profile again.")
        active = current or audit
        if active and active["project"].casefold() != project:
            raise ValueError("Choose an independent inspection for this project.")
        profile, updated_audit = preview[2][project], preview[3].get(project, audit)
        changed = key_for([current, audit]) != key_for([{key: value for key, value in profile.items() if key != "evidence"}, updated_audit])
        with self.conn:
            if changed:
                self.conn.execute("INSERT OR REPLACE INTO project_pack_backup VALUES(?,?,?)", (job, json.dumps(current), json.dumps(audit)))
            self.app.project_registry.save_profile(job, profile)
            if updated_audit:
                self.app.project_audit.save_audit(job, updated_audit)
        return self.status(job)

    def rollback(self, job):
        self.app.project_registry._root(job)
        previous = self.conn.execute("SELECT profile,audit FROM project_pack_backup WHERE job=?", (job,)).fetchone()
        if previous is None:
            raise ValueError("There is no prior pack state to restore.")
        profile, audit = map(json.loads, previous)
        with self.conn:
            if profile:
                self.app.project_registry.save_profile(job, profile)
            else:
                self.conn.execute("DELETE FROM project_profiles WHERE job=?", (job,))
            if audit:
                self.app.project_audit.save_audit(job, audit)
            else:
                self.app.project_audit.forget(job)
            self.conn.execute("DELETE FROM project_pack_backup WHERE job=?", (job,))
        return self.status(job)

    def status(self, job):
        profile, audit = self._current(job)
        return {"project": profile["project"] if profile else None, "rules": len(profile["rules"]) if profile else 0,
                "audit": bool(audit), "rollback": bool(self.conn.execute("SELECT 1 FROM project_pack_backup WHERE job=?", (job,)).fetchone())}

    def forget(self, job):
        self.tickets = {key: value for key, value in self.tickets.items() if value[0] != job}
        self.conn.execute("DELETE FROM project_pack_backup WHERE job=?", (job,))
