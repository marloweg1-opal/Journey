"""A retained project registry bound to one authorized Navigator inspection."""

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
from uuid import uuid4

from core.file_paths import safe_metadata, signature
from core.project_registry import (
    CLAIM_TYPES, PROFILE_FORMAT, archive_claims, asset_name, claim_id, creation_index_claims, iso_date, key_for,
    profile_date, render_name, text_field,
)
from journey_navigator.links import ProtectedPath
from journey_planner.catalog import absolute_path, check_local_drive, component
from journey_vision.observe import IMAGE_FORMATS, image_bytes
from journey_vision.steward import VERSION_TOKEN


ARCHIVE_BYTES = 64 * 1024 * 1024
CLAIM_LIMIT = 20_000
REGISTRY_PAGE = 16
SCHEMA = """
CREATE TABLE IF NOT EXISTS project_profiles (
    job TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, revision TEXT NOT NULL, document TEXT NOT NULL,
    knowledge_version INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS project_imports (
    job TEXT NOT NULL, profile TEXT NOT NULL, digest TEXT NOT NULL, name TEXT NOT NULL, claims INTEGER NOT NULL,
    PRIMARY KEY(job,profile,digest)
);
CREATE TABLE IF NOT EXISTS project_claims (
    job TEXT NOT NULL, profile TEXT NOT NULL, id TEXT NOT NULL, name_key TEXT NOT NULL,
    related_key TEXT NOT NULL, claim TEXT NOT NULL, decision TEXT NOT NULL DEFAULT 'unreviewed', reviewed_at TEXT,
    PRIMARY KEY(job,profile,id)
);
CREATE INDEX IF NOT EXISTS project_claim_names ON project_claims(job,profile,name_key);
CREATE INDEX IF NOT EXISTS project_claim_relations ON project_claims(job,profile,related_key);
CREATE TABLE IF NOT EXISTS project_asset_dates (
    id INTEGER PRIMARY KEY, job TEXT NOT NULL, profile TEXT NOT NULL, digest TEXT NOT NULL, evidence TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS project_date_by_asset ON project_asset_dates(job,profile,digest,id);
CREATE INDEX IF NOT EXISTS project_transition_paths ON asset_transitions(job,scope,digest,from_path);
"""


def filename_key(path):
    return Path(path).name.casefold() if isinstance(path, (str, Path)) else ""


def lifecycle(names, evidence):
    states = set()
    for claim in evidence:
        if claim["decision"] != "accepted":
            continue
        if claim["kind"] == "lifecycle" and filename_key(claim["name"]) in names:
            states.add(claim["value"])
        elif (claim["kind"] == "relationship" and claim["value"]["relation"] in ("supersedes", "replaces")
              and filename_key(claim["value"]["asset"]) in names):
            states.add("superseded")
    if len(states) > 1:
        return "conflicted"
    return next(iter(states), "unestablished")


def validate_profile(value):
    if not isinstance(value, dict) or value.get("format") != PROFILE_FORMAT:
        raise ValueError("Choose a Journey project naming profile.")
    project = text_field(value["project"], 80)
    signals, rules = value["signals"], value["rules"]
    if not isinstance(signals, list) or not 1 <= len(signals) <= 20:
        raise ValueError("A project profile needs 1–20 project or asset search terms.")
    signals = [text_field(item, 80) for item in signals]
    if not isinstance(rules, list) or not 1 <= len(rules) <= 20:
        raise ValueError("A project profile needs 1–20 supported naming rules.")
    validated = []
    classes = set()
    for rule in rules:
        subject, purpose = text_field(rule["subject"], 80), text_field(rule["purpose"], 80)
        prefix = component(rule["prefix"])
        extension = rule["extension"]
        if extension not in IMAGE_FORMATS or rule["date_order"] != "DD_MM":
            raise ValueError("Use a supported image extension and the DD_MM date format.")
        asset_class = (subject.casefold(), purpose.casefold(), extension)
        if asset_class in classes:
            raise ValueError("The profile contains conflicting rules for one image class.")
        classes.add(asset_class)
        example = rule["example"]
        example_date = iso_date(example["date"])
        if render_name(rule, example_date, extension) != component(example["filename"]):
            raise ValueError("The naming rule does not reproduce its dated example exactly.")
        validated.append({"subject": subject, "purpose": purpose, "prefix": prefix, "extension": extension,
                          "date_order": "DD_MM", "example": {"date": example_date, "filename": example["filename"]},
                          "source": text_field(rule["source"], 400)})
    return {"format": PROFILE_FORMAT, "project": project, "signals": signals, "rules": validated}


def validate_claim(claim):
    name, kind = claim["name"], claim["kind"]
    if name != asset_name(name) or kind not in CLAIM_TYPES:
        raise ValueError("The profile includes invalid registry evidence.")
    component(name)
    source = claim["source"]
    role = source["role"]
    if role not in ("user", "assistant", "creation_record"):
        raise ValueError("The registry evidence needs an attributed source.")
    origin = {key: text_field(source[key], 160) for key in ("archive", "conversation", "message")}
    origin["role"] = role
    authored = source.get("authored")
    origin["authored"] = text_field(authored, 60) if authored else None
    value = claim["value"]
    if kind == "reference":
        value = ""
    elif kind == "creation_date":
        value = iso_date(value)
    elif kind == "lifecycle":
        if value not in ("retired", "archived", "discarded"):
            raise ValueError("Unrecognized project lifecycle evidence.")
    else:
        relation, related = value["relation"], value["asset"]
        if relation not in ("supersedes", "replaces", "variant of", "derived from") or related != asset_name(related):
            raise ValueError("Unrecognized project relationship evidence.")
        value = {"relation": relation, "asset": component(related)}
    return {"name": name, "kind": kind, "value": value, "source": origin}


class ProjectRegistry:
    def __init__(self, app):
        self.app = app
        self.conn = app.conn
        self.conn.create_function("registry_filename", 1, filename_key, deterministic=True)
        self.conn.create_function("registry_asset", 1, asset_name, deterministic=True)
        self.conn.executescript(SCHEMA)

    def _root(self, job_id):
        if not self.app.retains:
            raise ProtectedPath("Keep a local checkpoint to retain a project registry.")
        job = self.app.job(job_id)
        self.app.policy.refresh()
        self.app._validate_scope(job, job["root"])
        return job

    def profile(self, job_id):
        row = self.conn.execute("SELECT * FROM project_profiles WHERE job=?", (job_id,)).fetchone()
        return (json.loads(row["document"]) | {key: row[key] for key in ("fingerprint", "revision", "knowledge_version")}) if row else None

    def _changed(self, job_id):
        self.conn.execute("UPDATE project_profiles SET knowledge_version=knowledge_version+1 WHERE job=?", (job_id,))

    def activate(self, job_id, value):
        self._root(job_id)
        profile = validate_profile(value)
        fingerprint = key_for(profile)
        evidence = value.get("evidence", [])
        if not isinstance(evidence, list) or len(evidence) > 100:
            raise ValueError("A profile can include at most 100 source-linked starter records.")
        seed = [validate_claim(claim) for claim in evidence]
        with self.conn:
            self.conn.execute("""INSERT INTO project_profiles(job,fingerprint,revision,document) VALUES(?,?,?,?) ON CONFLICT(job) DO UPDATE
                SET fingerprint=excluded.fingerprint,revision=excluded.revision,document=excluded.document
                WHERE project_profiles.fingerprint<>excluded.fingerprint""",
                (job_id, fingerprint, uuid4().hex, json.dumps(profile)))
            if self._insert(job_id, fingerprint, {claim_id(claim): claim for claim in seed}):
                self._changed(job_id)
        return self.profile(job_id)

    def deactivate(self, job_id):
        self._root(job_id)
        with self.conn:
            self.conn.execute("DELETE FROM project_profiles WHERE job=?", (job_id,))
        return {"active": False}

    def forget(self, job_id):
        # Caller already holds the checkpoint cleanup transaction.
        for table in ("project_profiles", "project_imports", "project_claims", "project_asset_dates"):
            self.conn.execute(f"DELETE FROM {table} WHERE job=?", (job_id,))

    def _insert(self, job_id, profile, claims):
        before = self.conn.total_changes
        self.conn.executemany("INSERT OR IGNORE INTO project_claims(job,profile,id,name_key,related_key,claim) VALUES(?,?,?,?,?,?)",
            ((job_id, profile, key, filename_key(claim["name"]),
              filename_key(claim["value"]["asset"]) if claim["kind"] == "relationship" else "", json.dumps(claim))
             for key, claim in claims.items()))
        count = self.conn.execute("SELECT count(*) FROM project_claims WHERE job=? AND profile=?",
                                  (job_id, profile)).fetchone()[0]
        if count > CLAIM_LIMIT:
            raise ValueError("This registry has reached its retained evidence limit.")
        return self.conn.total_changes - before

    def _archive_access(self, path):
        self.app.policy.check(path)
        for scope, mode, permissions, _ in self.app.policy.perception:
            if path.is_relative_to(scope):
                if (mode != "OPEN" or not isinstance(permissions, dict)
                        or permissions.get("inference_permission") is False
                        or permissions.get("semantic_retention_permission") is not True):
                    raise ProtectedPath("An existing Journey policy restricts reading or retaining this history.")
                break

    def import_archive(self, job_id, selected):
        self._root(job_id)
        profile = self.profile(job_id)
        if not profile:
            raise ValueError("Choose the project profile for this inspection before importing history.")
        path = absolute_path(selected)
        check_local_drive(path)
        before = safe_metadata(path, read_guard=self._archive_access)
        if path.suffix.casefold() != ".json" or not stat.S_ISREG(before.st_mode) or before.st_size > ARCHIVE_BYTES:
            raise ValueError("Choose one regular local JSON export no larger than 64 MiB.")
        with path.open("rb") as stream:
            if signature(os.fstat(stream.fileno())) != signature(before):
                raise ValueError("The selected export changed before reading.")
            data = stream.read(ARCHIVE_BYTES + 1)
        if len(data) != before.st_size or signature(safe_metadata(path, read_guard=self._archive_access)) != signature(before):
            raise ValueError("The selected export changed while reading.")
        digest = sha256(data).hexdigest()
        key = (job_id, profile["fingerprint"])
        if self.conn.execute("SELECT 1 FROM project_imports WHERE job=? AND profile=? AND digest=?", (*key, digest)).fetchone():
            return {"added": 0, "already_imported": True}
        try:
            document = json.loads(data.decode("utf-8-sig"))
            signals = [profile["project"], *profile["signals"]]
            if isinstance(document, dict) and document.get("version") == 1 and isinstance(document.get("entries"), dict):
                claims = creation_index_claims(document, path.name, signals)
            else:
                claims = archive_claims(document, path.name, signals)
        except (UnicodeError, RecursionError, json.JSONDecodeError) as error:
            raise ValueError("The selected export is not readable conversation JSON.") from error
        with self.conn:
            added = self._insert(*key, claims)
            self.conn.execute("INSERT INTO project_imports VALUES(?,?,?,?,?)", (*key, digest, path.name, len(claims)))
            self._changed(job_id)
        return {"added": added, "already_imported": False}

    def _evidence(self, job_id, profile, names):
        if not names:
            return []
        marks = ",".join("?" for _ in names)
        rows = self.conn.execute(f"""SELECT id,claim,decision,reviewed_at FROM project_claims
            WHERE job=? AND profile=? AND (name_key IN ({marks}) OR related_key IN ({marks}))
            ORDER BY decision='rejected', json_extract(claim,'$.kind')='reference',id LIMIT 25""",
            (job_id, profile, *names, *names))
        return [json.loads(row["claim"]) | {key: row[key] for key in ("id", "decision", "reviewed_at")} for row in rows]

    def catalog(self, job_id, offset):
        job = self._root(job_id)
        profile = self.profile(job_id)
        if not profile:
            return {"profile": None, "items": [], "more": False}
        key = (job_id, profile["fingerprint"])
        scope = (job_id, job["root"])
        names = [row[0] for row in self.conn.execute("""SELECT name_key FROM project_claims WHERE job=? AND profile=?
            UNION SELECT registry_filename(path) FROM files WHERE job=? AND scope=? AND epoch=? AND registry_asset(path)<>''
            ORDER BY name_key LIMIT ? OFFSET ?""", (*key, *scope, job["epoch"], REGISTRY_PAGE + 1, offset))]
        marks = ",".join("?" for _ in names[:REGISTRY_PAGE])
        candidates = {}
        if names:
            page_names = names[:REGISTRY_PAGE]
            rows = self.conn.execute(f"""WITH RECURSIVE lineage(name_key,path,digest) AS (
                    SELECT registry_filename(from_path),to_path,digest FROM asset_transitions
                    WHERE job=? AND scope=? AND registry_filename(from_path) IN ({marks})
                    UNION SELECT lineage.name_key,t.to_path,t.digest FROM lineage
                    JOIN asset_transitions t ON t.from_path=lineage.path AND t.digest=lineage.digest
                    WHERE t.job=? AND t.scope=?
                ), current AS (
                    SELECT path,digest,registry_filename(path) AS name_key FROM files WHERE job=? AND scope=? AND epoch=?
                )
                SELECT path,name_key,0 AS historical FROM current WHERE name_key IN ({marks})
                UNION SELECT f.path,lineage.name_key,1 FROM current f JOIN lineage ON f.path=lineage.path AND f.digest=lineage.digest
                ORDER BY path""", (*scope, *page_names, *scope, *scope, job["epoch"], *page_names))
            for row in rows:
                try:
                    path = self.app.policy.check_image(row["path"], retain=True)
                    safe_metadata(path)
                except (OSError, ValueError):
                    continue
                matches = candidates.setdefault(row["name_key"], {})
                matches[row["path"]] = bool(row["historical"]) or matches.get(row["path"], False)
        coverage = self.app.summary(job_id)
        complete = not any(coverage[key] for key in ("pending", "pending_folders", "skipped", "link_attention"))
        items = []
        for name in names[:REGISTRY_PAGE]:
            evidence = self._evidence(*key, [name])
            matches = candidates.get(name, {})
            paths = list(matches)
            if not evidence and not paths:
                continue
            if len(paths) > 1:
                state = "multiple_candidates"
            elif not paths:
                state = "referenced_not_located" if complete else "not_yet_located"
            elif matches[paths[0]]:
                state = "verified_path_history"
            else:
                state = "filename_candidate" if evidence else "observed_in_scope"
            named = next((item["name"] for item in evidence if filename_key(item["name"]) == name), None)
            items.append({"name": named or (Path(paths[0]).name if paths else name),
                          "state": state, "paths": paths[:5], "matches": len(paths),
                          "lifecycle": lifecycle({name}, evidence), "evidence": evidence})
        return {"profile": profile, "items": items, "more": len(names) > REGISTRY_PAGE,
                "claims": self.conn.execute("SELECT count(*) FROM project_claims WHERE job=? AND profile=?", key).fetchone()[0],
                "archives": self.conn.execute("SELECT count(*) FROM project_imports WHERE job=? AND profile=?", key).fetchone()[0]}

    def review(self, job_id, claim, decision):
        self._root(job_id)
        profile = self.profile(job_id)
        if not profile or decision not in ("accepted", "rejected", "unreviewed"):
            raise ValueError("Choose an evidence record and its review disposition.")
        with self.conn:
            result = self.conn.execute("""UPDATE project_claims SET decision=?,reviewed_at=?
                WHERE job=? AND profile=? AND id=?""",
                (decision, datetime.now(timezone.utc).isoformat(), job_id, profile["fingerprint"], claim))
            if not result.rowcount:
                raise ValueError("Choose evidence from the active project registry.")
            self._changed(job_id)
        return {"saved": True}

    def _history(self, job, row):
        current = row["path"]
        history = []
        for transition in self.conn.execute("""SELECT from_path,to_path,receipt FROM asset_transitions
                WHERE job=? AND scope=? AND digest=? ORDER BY id DESC""", (job["id"], row["scope"], row["digest"])):
            if transition["to_path"] != current:
                continue
            current = transition["from_path"]
            try:
                self.app.policy.check_image(current, retain=True)
            except ProtectedPath:
                break
            history.append(dict(transition))
            if len(history) == 20:
                break
        return history

    def record_date(self, job_id, asset, value, source_note, evidence_id=None):
        job = self._root(job_id)
        profile = self.profile(job_id)
        if not profile:
            raise ValueError("Choose the project profile before recording an asset creation date.")
        row = self.conn.execute("""SELECT * FROM files WHERE id=? AND job=? AND scope=? AND epoch=? AND status='analyzed'""",
                                (asset, job_id, job["root"], job["epoch"])).fetchone()
        if row is None:
            raise ValueError("Choose a current image in the registry's inspection folder.")
        path = self.app.policy.check_image(row["path"], retain=True, learn=True)
        if sha256(image_bytes(path)).hexdigest() != row["digest"]:
            raise ValueError("The image changed. Refresh its folder before recording the date.")
        origin = {"type": "operator_confirmation", "source": text_field(source_note, 300)} if not evidence_id else None
        if evidence_id:
            names = {filename_key(path), *(filename_key(item["from_path"]) for item in self._history(job, row))}
            evidence = next((item for item in self._evidence(job_id, profile["fingerprint"], sorted(names))
                             if item["id"] == evidence_id and item["kind"] == "creation_date"
                             and item["decision"] != "rejected"), None)
            if evidence is None:
                raise ValueError("Choose current date evidence for this exact image.")
            value = evidence["value"]
            origin = {"type": "operator_confirmed_archive", "source": evidence["source"], "claim": evidence_id}
        entry = origin | {"date": iso_date(value), "confirmed_at": datetime.now(timezone.utc).isoformat()}
        with self.conn:
            self.conn.execute("INSERT INTO project_asset_dates(job,profile,digest,evidence) VALUES(?,?,?,?)",
                              (job_id, profile["fingerprint"], row["digest"], json.dumps(entry)))
            self._changed(job_id)
        return {"saved": True}

    def details(self, job, row, features, profile, record):
        history = self._history(job, row) if profile else []
        names = {filename_key(row["path"]), *(filename_key(item["from_path"]) for item in history)}
        evidence = self._evidence(job["id"], profile["fingerprint"], sorted(names)) if profile else []
        decisions = [json.loads(item[0]) for item in self.conn.execute("""SELECT evidence FROM project_asset_dates
            WHERE job=? AND profile=? AND digest=? ORDER BY id DESC LIMIT 20""",
            (job["id"], profile["fingerprint"], row["digest"]))] if profile else []
        embedded = features.get("creation_dates", [])
        dates = {item["date"] for item in embedded}
        chosen = decisions[0] if decisions else (embedded[0] if len(dates) == 1 else None)
        rule = None
        if profile:
            key = (record["identity"]["label"].casefold(), record["purpose"]["label"].casefold(), Path(row["path"]).suffix.casefold())
            rule = next((rule for rule in profile["rules"]
                         if (rule["subject"].casefold(), rule["purpose"].casefold(), rule["extension"]) == key), None)
        short = profile_date(rule, Path(row["path"]).name) if rule else None
        archive_rejected = bool(chosen and chosen.get("claim") and self.conn.execute(
            "SELECT 1 FROM project_claims WHERE job=? AND profile=? AND id=? AND decision='rejected'",
            (job["id"], profile["fingerprint"], chosen["claim"])).fetchone())
        short_disagrees = bool(chosen and short and short["state"] == "observed"
                               and chosen["date"][5:] != f"{short['month']:02d}-{short['day']:02d}")
        conflict = archive_rejected or (not decisions and (len(dates) > 1 or short_disagrees))
        return rule, {
            "original_filename": Path(history[-1]["from_path"] if history else row["path"]).name,
            "current_filename": Path(row["path"]).name, "filesystem_modified_ns": row["modified"],
            "date": chosen if not conflict else None, "date_state": "conflicted" if conflict else ("known" if chosen else "unknown"),
            "filename_date": short, "embedded_dates": embedded, "date_reviews": decisions,
            "path_history": list(reversed(history)), "registry_evidence": evidence, "lifecycle": lifecycle(names, evidence),
        }


def preview(path, record, metadata, rule):
    result = {"destination": None, "state": "held_convention", "executable": False}
    if not rule:
        return result | {"reason": "The active profile has no validated rule for this subject, asset type, and extension."}
    if record["identity"]["state"] != "human_confirmed_identity" or record["purpose"]["state"] != "human_confirmed":
        return result | {"state": "needs_identification", "reason": "Confirm the subject and purpose before reviewing a rename."}
    if not metadata["date"]:
        reason = ("Creation date evidence disagrees. Review the competing dates."
                  if metadata["date_state"] == "conflicted" else "A full asset creation date is needed. The file modification date is separate.")
        return result | {"state": "needs_date", "reason": reason}
    name = component(render_name(rule, metadata["date"]["date"], path.suffix))
    if name == path.name:
        return result | {"state": "matches_rule", "reason": "The filename already matches the validated profile."}
    if VERSION_TOKEN.search(path.stem):
        return result | {"state": "blocked", "reason": "The source name contains a version or variation and this profile has no rule for preserving it."}
    return {"state": "proposed", "destination": name, "executable": True,
            "reason": "Uses the confirmed subject and purpose and the evidenced creation date with the validated DD_MM rule."}
