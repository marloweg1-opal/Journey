"""Bounded, scoped retirement planning for Navigator's existing Patrol."""

from collections import deque
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
from time import monotonic

from core.dependency_evidence import TEXT_EXTENSIONS, reference_match
from core.file_paths import is_link, safe_metadata, signature
from core.naming_audit import contains_words, words
from core.project_registry import key_for, text_field
from core.recovery_inspection import file_identity
from journey_navigator.conversation import explicit_intent, validate_prompt
from journey_navigator.links import ProtectedPath
from journey_planner.catalog import absolute_path
from journey_vision.observe import IMAGE_FORMATS


MAX_CANDIDATES = 60
MAX_SELECTION = 20
PLAN_SECONDS = 600
REFERENCE_ENTRIES = 1800
REFERENCE_FILES = 60
REFERENCE_BYTES = 512_000
REFERENCE_SECONDS = 2
DOCS = frozenset({".md", ".txt"})
HISTORY = ("history", "historical", "reference", "comparison", "archive", "archived", "retired", "quarantine")
SCHEMA = """
CREATE TABLE IF NOT EXISTS stewardship_retirements (
    id INTEGER PRIMARY KEY,job TEXT NOT NULL,project TEXT NOT NULL,decision TEXT NOT NULL,
    path TEXT NOT NULL,digest TEXT NOT NULL,fact TEXT NOT NULL,UNIQUE(job,project,decision,path)
);
CREATE INDEX IF NOT EXISTS stewardship_asset ON stewardship_retirements(job,project,digest,path,id);
"""


def family_match(path, root, family):
    path, root = Path(path), Path(root)
    if not path.is_relative_to(root):
        return False
    return contains_words(str(Path(root.name) / path.relative_to(root)), family)


def history_entry(path, root):
    relative = Path(path).relative_to(root)
    return any(contains_words(str(relative), term) for term in HISTORY)


def project_key(profile):
    return profile["project"] if profile else ""


def retirement_facts(conn, job, profile, path, digest, history):
    names = {path, *(item["from_path"] for item in history)}
    slots = ",".join("?" for _ in names)
    rows = conn.execute(f"""SELECT fact FROM stewardship_retirements
        WHERE job=? AND project=? AND digest=? AND path IN ({slots}) ORDER BY id DESC LIMIT 20""",
        (job, project_key(profile), digest, *sorted(names)))
    return [json.loads(row["fact"]) for row in rows]


def _policy_for_reference(policy, path):
    policy.check(path)
    for scope, mode, permissions, purposes in policy.perception:
        if path.is_relative_to(scope):
            if (mode not in ("OPEN", "LIMITED") or "dependency_inspection" not in purposes
                    or not isinstance(permissions, dict) or permissions.get("inference_permission") is not True
                    or permissions.get("semantic_retention_permission") is not True):
                raise ProtectedPath("Reference inspection requires the existing dependency-reading permission.")
            break


def _read_reference(policy, path, remaining):
    _policy_for_reference(policy, path)
    before = safe_metadata(path, read_guard=policy.check)
    if not stat.S_ISREG(before.st_mode) or before.st_size > min(64_000, remaining):
        raise ValueError("Reference file exceeds the read budget or changed type.")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if signature(opened) != signature(before) or opened.st_size != before.st_size:
            raise ValueError("Reference changed before reading.")
        data = stream.read(before.st_size + 1)
        finished = os.fstat(stream.fileno())
    after = safe_metadata(path, read_guard=policy.check)
    _policy_for_reference(policy, path)
    if len(data) != before.st_size or signature(finished) != signature(before) or signature(after) != signature(before):
        raise ValueError("Reference changed during reading.")
    text = data.decode("utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
    return text.casefold(), sha256(data).hexdigest()


def scan_references(app, root, sources):
    """Inspect only bounded, explicitly authorized local reference content."""
    root = Path(root)
    queue = deque([root])
    deadline = monotonic() + REFERENCE_SECONDS
    budget = REFERENCE_BYTES
    entries = checked = gaps = 0
    matches = []
    while queue and entries < REFERENCE_ENTRIES and checked < REFERENCE_FILES and monotonic() < deadline:
        directory = queue.popleft()
        try:
            app.policy.check(directory)
            safe_metadata(directory, read_guard=app.policy.check)
            with os.scandir(directory) as scan:
                for entry in scan:
                    entries += 1
                    if entries > REFERENCE_ENTRIES or checked >= REFERENCE_FILES or budget <= 0 or monotonic() >= deadline:
                        gaps += 1
                        break
                    path = Path(entry.path)
                    try:
                        app.policy.check(path)
                        info = entry.stat(follow_symlinks=False)
                        if is_link(info) or path.suffix.casefold() == ".lnk":
                            gaps += 1
                            continue
                        if stat.S_ISDIR(info.st_mode):
                            queue.append(path)
                            continue
                        if not stat.S_ISREG(info.st_mode) or path.suffix.casefold() not in TEXT_EXTENSIONS | DOCS:
                            continue
                        # Account for bytes and files even if a later parse or read fails.
                        checked += 1
                        allowance = min(64_000, budget)
                        budget -= min(info.st_size, allowance)
                        content, fingerprint = _read_reference(app.policy, path, allowance)
                        role = "documentation" if path.suffix.casefold() in DOCS else "possible_dependency"
                        for target in sources:
                            match = reference_match(target, content)
                            if match:
                                if len(matches) >= 180:
                                    gaps += 1
                                    break
                                matches.append({"target": target, "reference": str(path), "match": match,
                                                "fingerprint": fingerprint, "role": role})
                    except (OSError, ValueError):
                        gaps += 1
        except (OSError, ValueError):
            gaps += 1
    complete = not (gaps or queue)
    return {"state": "CHECKED_WITHIN_SCOPE" if complete else "INSUFFICIENT_EVIDENCE",
            "files_checked": checked, "entries_seen": entries, "gaps": gaps + len(queue),
            "references": matches, "global_clearance": False}


class Stewardship:
    def __init__(self, patrol):
        self.patrol = patrol
        self.app = patrol.app
        self.conn = patrol.conn
        self.plans = {}
        self.conn.create_function("retirement_family_match", 3, family_match, deterministic=True)

    def clear(self):
        self.plans.clear()

    def invalidate(self, job):
        self.plans = {key: item for key, item in self.plans.items() if item["job"] != job}

    def _context(self, destination):
        task = self.patrol.row(destination)
        job = self.app.job(task["job"])
        profile = self.app.project_registry.profile(job["id"])
        basis = [job["root"], job["epoch"], profile["revision"] if profile else None,
                 profile["knowledge_version"] if profile else None]
        return job, profile, basis

    def _claim_sources(self, job, profile, family):
        if not profile:
            return []
        rows = self.conn.execute("""SELECT id,claim,decision FROM project_claims
            WHERE job=? AND profile=? AND retirement_family_match(
                ? || '/' || json_extract(claim,'$.name'), ?, ?)
            ORDER BY decision='accepted' DESC,id LIMIT 25""",
            (job["id"], profile["fingerprint"], job["root"], job["root"], family))
        return [json.loads(row["claim"]) | {"id": row["id"], "decision": row["decision"]} for row in rows]

    def _path_restriction(self, path):
        try:
            self.patrol.guided.require_unprotected(path)
        except (OSError, ValueError) as error:
            return str(error)
        return ""

    def plan(self, destination, instruction, *, provider=None, read_references=False):
        job, profile, basis = self._context(destination)
        if type(read_references) is not bool:
            raise ValueError("Choose whether to read scoped reference files.")
        instruction = validate_prompt(instruction)
        direct = explicit_intent(instruction)
        proposed = provider.get("family") if provider else None
        provider_state = provider["state"] if provider else "DISABLED"
        disagreement = direct and proposed and words(direct) != words(proposed)
        family = None if disagreement else (direct or proposed)
        if not family:
            return {"state": "NEEDS_HUMAN_DECISION", "provider": provider_state,
                    "reason": "Name one design family and give an affirmative retirement instruction."}
        coverage = self.app.summary(job["id"])
        if coverage["pending_folders"] or coverage["pending"]:
            return {"state": "INSUFFICIENT_EVIDENCE", "provider": provider_state,
                    "reason": "Finish the current folder inspection before preparing a retirement review."}
        rows = self.conn.execute("""SELECT * FROM files
            WHERE job=? AND epoch=? AND scope=? AND retirement_family_match(path,?,?)
            ORDER BY path LIMIT ?""", (job["id"], job["epoch"], job["root"], job["root"], family, MAX_CANDIDATES + 1)).fetchall()
        if len(rows) > MAX_CANDIDATES:
            return {"state": "INSUFFICIENT_EVIDENCE", "provider": provider_state,
                    "reason": "Too many matches. Name a narrower design family or use a smaller authorized folder."}
        entries, held = [], 0
        for row in rows:
            path = Path(row["path"])
            is_image = path.suffix.casefold() in IMAGE_FORMATS
            try:
                self.app.policy.check(path)
                if is_image:
                    self.app.policy.check_image(path, retain=True)
                observed = safe_metadata(path, read_guard=self.app.policy.check)
                if (observed.st_size, observed.st_mtime_ns) != (row["size"], row["modified"]):
                    held += 1
                    continue
            except (OSError, ValueError):
                held += 1
                continue
            history = history_entry(path, job["root"])
            group = ("historical_reference" if history or path.suffix.casefold() in DOCS else
                     "asset_candidate" if is_image and row["status"] == "analyzed" else "needs_identification")
            evidence = self.app.project_registry._evidence(job["id"], profile["fingerprint"], [path.name.casefold()]) if profile else []
            entries.append({"id": row["id"], "path": str(path), "group": group, "digest": row["digest"],
                            "file_identity": [observed.st_dev, observed.st_ino],
                            "physical_blocker": self._path_restriction(path) if group == "asset_candidate" else "",
                            "evidence": evidence[:8]})
        assets = [item["path"] for item in entries if item["group"] == "asset_candidate"]
        refs = scan_references(self.app, job["root"], assets) if read_references and assets else {
            "state": "NO_AUTHORITY" if assets else "INSUFFICIENT_EVIDENCE",
            "files_checked": 0, "entries_seen": 0, "gaps": 0, "references": [], "global_clearance": False}
        dependencies = {ref["target"] for ref in refs["references"] if ref["role"] == "possible_dependency"}
        for item in entries:
            item["copy_paths"] = [str(row[0]) for row in self.conn.execute("""SELECT path FROM files
                WHERE job=? AND scope=? AND epoch=? AND digest=? AND path<>? ORDER BY path LIMIT 6""",
                (job["id"], job["root"], job["epoch"], item["digest"], item["path"]))
                if self._visible_copy(row[0])]
            if item["path"] in dependencies:
                item["physical_blocker"] = item["physical_blocker"] or "A current configuration references this asset."
        archives = self._claim_sources(job, profile, family)
        result = {"state": "AWAITING_REVIEW" if entries or archives else "INSUFFICIENT_EVIDENCE",
                  "provider": provider_state, "family": family, "scope": job["root"], "entries": entries,
                  "withheld_or_changed": held, "archive_evidence": archives, "dependencies": refs,
                  "questions": {"inventory": "CANDIDATE" if entries else "INSUFFICIENT_EVIDENCE",
                                "provenance": "CANDIDATE" if archives or any(item["evidence"] for item in entries) else "INSUFFICIENT_EVIDENCE",
                                "dependencies": refs["state"],
                                "disposition": "NEEDS_HUMAN_DECISION" if assets else "INSUFFICIENT_EVIDENCE"}}
        binding = key_for([destination, basis, result])
        self.plans = {key: value for key, value in self.plans.items() if monotonic() - value["at"] < PLAN_SECONDS}
        if len(self.plans) >= 12 and binding not in self.plans:
            self.plans.pop(next(iter(self.plans)))
        self.plans[binding] = {"destination": destination, "job": job["id"], "basis": basis,
                               "result": result, "at": monotonic(), "read_references": read_references}
        return result | {"binding": binding}

    def _visible_copy(self, path):
        try:
            self.app.policy.check_image(path, retain=True)
            safe_metadata(Path(path), read_guard=self.app.policy.check)
            return True
        except (OSError, ValueError):
            return False

    def _selection(self, destination, binding, selected):
        job, profile, basis = self._context(destination)
        item = self.plans.get(binding)
        if (not item or item["destination"] != destination or item["basis"] != basis
                or monotonic() - item["at"] >= PLAN_SECONDS):
            raise ValueError("The retirement review expired or its scope changed. Inspect the instruction again.")
        if (not isinstance(selected, list) or not 1 <= len(selected) <= MAX_SELECTION
                or any(type(identifier) is not int for identifier in selected) or len(set(selected)) != len(selected)):
            raise ValueError("Select 1–20 distinct current asset candidates.")
        entries = {entry["id"]: entry for entry in item["result"]["entries"] if entry["group"] == "asset_candidate"}
        chosen = []
        for identifier in selected:
            if identifier not in entries:
                raise ValueError("Choose asset candidates. Historical references stay separate.")
            entry = entries[identifier]
            path = self.app.policy.check_image(entry["path"], retain=True, learn=True)
            actual = file_identity(path, max_bytes=16 * 1024 * 1024, read_guard=self.app.policy.check)
            if actual is None or actual["sha256"] != entry["digest"]:
                raise ValueError("A selected asset changed. Refresh and prepare the retirement again.")
            if [actual["device"], actual["inode"]] != entry["file_identity"]:
                raise ValueError("The selected path now contains a different file. Review the retirement again.")
            chosen.append(entry)
        return job, profile, item, chosen

    def confirm(self, destination, binding, selected, reason, replacement=""):
        job, profile, item, chosen = self._selection(destination, binding, selected)
        reason = text_field(reason, 300)
        replacement = text_field(replacement, 180) if replacement else None
        family = item["result"]["family"]
        decision = key_for([binding, sorted(selected), reason, replacement])
        with self.conn:
            for entry in chosen:
                fact = {"state": "retired", "family": family, "reason": reason, "replacement": replacement,
                        "source": {"type": "operator_confirmed_retirement", "destination": destination, "decision": decision,
                                   "recorded_at": datetime.now(timezone.utc).isoformat()},
                        "path": entry["path"], "digest": entry["digest"],
                        "provenance": [value["source"] for value in entry["evidence"]],
                        "dependencies": [ref for ref in item["result"]["dependencies"]["references"] if ref["target"] == entry["path"]],
                        "physical_blocker": entry["physical_blocker"]}
                self.conn.execute("""INSERT OR IGNORE INTO stewardship_retirements(job,project,decision,path,digest,fact)
                    VALUES(?,?,?,?,?,?)""", (job["id"], project_key(profile), decision, entry["path"], entry["digest"], json.dumps(fact)))
        return {"state": "VERIFIED_COMPLETE", "decision": decision, "recorded": len(chosen)}

    def _confirmed(self, job, profile, decision, path, digest):
        row = self.conn.execute("""SELECT 1 FROM stewardship_retirements
            WHERE job=? AND project=? AND decision=? AND path=? AND digest=?""",
            (job["id"], project_key(profile), decision, path, digest)).fetchone()
        if row is None:
            raise ValueError("Record an explicit retirement decision for each selected asset first.")

    def archive(self, destination, binding, selected, decision, folder):
        job, profile, item, chosen = self._selection(destination, binding, selected)
        if not item["read_references"]:
            raise PermissionError("Enable the scoped dependency reading step before preparing a physical archive batch.")
        target = absolute_path(folder)
        scope = Path(job["root"])
        if target == scope or not target.is_relative_to(scope):
            raise ValueError("Choose an existing archive folder inside the reviewed project scope.")
        if not stat.S_ISDIR(safe_metadata(target, read_guard=self.app.policy.check).st_mode):
            raise ValueError("Choose an existing archive folder.")
        operations = []
        for entry in chosen:
            self._confirmed(job, profile, decision, entry["path"], entry["digest"])
            operations.append({"kind": "move", "asset": entry["id"], "destination": str(target / Path(entry["path"]).name),
                               "reason": "Archive an explicitly retired asset while preserving the source name and history."})
        request_key = key_for([item["basis"], decision, sorted(operation["destination"] for operation in operations)])
        guided = self.patrol.guided
        prior = guided.conn.execute("""SELECT id FROM guided_batches WHERE job=?
            AND json_extract(payload,'$.operations[0].retirement.request')=? ORDER BY created DESC LIMIT 1""",
            (job["id"], request_key)).fetchone()
        if prior:
            return guided.view(prior["id"])
        return guided.prepare(job["id"], operations, retirement={
            "decision": decision, "basis": item["basis"], "request": request_key})

    def verify_archive(self, job_id, operation):
        job = self.app.job(job_id)
        profile = self.app.project_registry.profile(job_id)
        record = operation["retirement"]
        basis = [job["root"], job["epoch"], profile["revision"] if profile else None,
                 profile["knowledge_version"] if profile else None]
        if basis != record["basis"]:
            raise ValueError("The source inspection or evidence changed. Prepare a new archive review.")
        path, digest = operation["source"], operation["identity"]["sha256"]
        self._confirmed(job, profile, record["decision"], path, digest)
        refs = scan_references(self.app, job["root"], [path])
        if any(item["role"] == "possible_dependency" for item in refs["references"]):
            raise PermissionError("A current configuration references this asset. Review its dependency before archiving.")
        if refs["state"] != "CHECKED_WITHIN_SCOPE":
            raise PermissionError("Scoped dependency coverage is incomplete. Keep this asset in place until it can be reviewed.")
