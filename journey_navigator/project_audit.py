"""Retained, read-only naming coverage for the selected project inspection."""

import json
from pathlib import Path
from time import monotonic

from core.file_paths import safe_metadata
from core.naming_audit import FIELDS, contains_words, resolve_field, validate_audit
from core.project_registry import asset_name, profile_date
from core.recovery_inspection import file_identity


MAX_ROWS = 2000
PROOF_FILES = 12
PROOF_BYTES = 32 * 1024 * 1024


class ProjectAudit:
    def __init__(self, app):
        self.app = app
        self.conn = app.conn
        self.conn.execute("CREATE TABLE IF NOT EXISTS project_naming_audits(job TEXT PRIMARY KEY, document TEXT NOT NULL)")

    def forget(self, job):
        self.conn.execute("DELETE FROM project_naming_audits WHERE job=?", (job,))

    def document(self, job):
        row = self.conn.execute("SELECT document FROM project_naming_audits WHERE job=?", (job,)).fetchone()
        return json.loads(row[0]) if row else None

    def activate(self, job_id, document):
        self.app.project_registry._root(job_id)
        audit = validate_audit(document)
        active = self.app.project_registry.profile(job_id)
        if active and active["project"].casefold() != audit["project"].casefold():
            raise ValueError("This naming audit belongs to another project. Choose its own inspection.")
        with self.conn:
            self.conn.execute("""INSERT INTO project_naming_audits VALUES(?,?)
                ON CONFLICT(job) DO UPDATE SET document=excluded.document""", (job_id, json.dumps(audit)))
        return {"saved": True, "project": audit["project"]}

    def _observed(self, job, document, active):
        rows = self.conn.execute("""SELECT path,status,digest,size,modified FROM files
            WHERE job=? AND epoch=? AND scope=? ORDER BY id LIMIT ?""",
            (job["id"], job["epoch"], job["root"], MAX_ROWS + 1)).fetchall()
        rules = {(rule["subject"], rule["purpose"], rule["extension"]): rule
                 for rule in (active["rules"] if active else [])}
        samples, found, count = {}, {}, 0
        budget, deadline = PROOF_BYTES, monotonic() + 2
        for row in rows[:MAX_ROWS]:
            path = Path(row["path"])
            if not asset_name(path.name):
                continue
            relative = str(path.relative_to(job["root"]))
            subjects = [name for name in document["subjects"] if any(contains_words(relative, alias)
                        for alias in [name, *document.get("aliases", {}).get(name, [])])]
            families = [entry["name"] for entry in document["families"] if any(contains_words(relative, word) for word in entry["terms"])]
            if len(subjects) != 1 or len(families) != 1:
                continue
            try:
                self.app.policy.check_image(path, retain=True)
                current = safe_metadata(path, read_guard=self.app.policy.check)
                if (current.st_size, current.st_mtime_ns) != (row["size"], row["modified"]):
                    continue
            except (OSError, ValueError):
                continue
            key = (subjects[0], families[0])
            found[key] = found.get(key, 0) + 1
            evidence = samples.setdefault(key, [])
            if len(evidence) == 3:
                continue
            file_proof = {"name": path.name, "path": str(path), "state": "OBSERVED_NAME", "sha256": None}
            rule = rules.get((*key, path.suffix.casefold()))
            short_date = profile_date(rule, path.name) if rule else None
            if (short_date and short_date["state"] in ("observed", "undated") and row["status"] == "analyzed"
                    and count < PROOF_FILES and 0 < row["size"] <= budget and monotonic() < deadline):
                count += 1
                budget -= row["size"]
                try:
                    actual = file_identity(path, max_bytes=row["size"], read_guard=self.app.policy.check)
                except (OSError, ValueError):
                    actual = None
                if actual and actual["sha256"] == row["digest"]:
                    file_proof.update(state="VERIFIED_FILENAME_EXEMPLAR", sha256=actual["sha256"])
            evidence.append(file_proof)
        return samples, found, len(rows) > MAX_ROWS

    def view(self, job_id):
        job = self.app.project_registry._root(job_id)
        document = self.document(job_id)
        if not document:
            return {"state": "NO_AUDIT", "items": []}
        active = self.app.project_registry.profile(job_id)
        if active and active["project"].casefold() != document["project"].casefold():
            return {"state": "CONFLICTED", "project": document["project"], "items": [],
                    "reason": "The active naming profile belongs to a different project."}
        examples, counts, limited = self._observed(job, document, active)
        items = []
        for subject in document["subjects"]:
            for family in document["families"]:
                key = (subject, family["name"])
                fields = {field: resolve_field(document["claims"], *key, field) for field in FIELDS}
                active_rules = [rule for rule in (active["rules"] if active else []) if (rule["subject"], rule["purpose"]) == key]
                files = examples.get(key, [])
                archived = [sample for sample in document.get("examples", [])
                            if (sample["subject"], sample["family"]) == key]
                if any(field["state"] == "CONFLICTED" for field in fields.values()):
                    state = "CONFLICTED"
                elif active_rules:
                    state = ("VERIFIED_FILENAME_EXEMPLAR" if any(item["state"] == "VERIFIED_FILENAME_EXEMPLAR" for item in files)
                             else "RULE_ONLY")
                else:
                    state = "CANDIDATE" if files or archived else "UNKNOWN"
                items.append({"subject": subject, "family": family["name"], "state": state, "fields": fields,
                              "active_rules": active_rules, "observed_count": counts.get(key, 0),
                              "files": files, "examples": archived})
        coverage = self.app.summary(job_id)
        return {"state": "REVIEWABLE", "project": document["project"], "items": items,
                "scan_limited": limited or bool(coverage["pending"] or coverage["pending_folders"]
                                                or coverage["skipped"] or coverage["link_attention"]),
                "active_rule_count": len(active["rules"]) if active else 0}
