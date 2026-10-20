"""Bounded Shadow patrol, scoped posture, and explicit delegated authority."""

import hashlib
import json
import math
import os
import stat
import time
from pathlib import Path

from core.placement import _is_under

LIFECYCLES = {"CONSTRUCTION", "CONVERGENCE", "STEWARDSHIP"}
PERMISSIONS = {"OBSERVE", "MAINTAIN", "STEWARD", "ASK"}
ATTENTION = {"SILENT", "DIGEST", "REVIEW_QUEUE", "NOTIFY", "INTERRUPT"}


def run_patrol(conn, *, scope, docs_root, cycles=1, interval=30, limit=500, stop=None):
    """Bounded foreground patrol. The caller owns scheduling and cancellation."""
    from core.shadow import run_shadow
    from core.patrol_state import read_state
    if not 1 <= cycles <= 20 or interval < 1:
        raise ValueError("Patrol requires 1..20 cycles and an interval of at least one second")
    results = []
    for cycle in range(cycles):
        if read_state(conn)['paused']:
            break
        if stop is not None and stop.is_set():
            break
        results.append(run_shadow(conn, scope=scope, docs_root=docs_root, limit=limit))
        if cycle + 1 < cycles:
            if stop is not None:
                if stop.wait(interval):
                    break
            else:
                time.sleep(interval)
    return results


def initialize_patrol(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS patrol_policy_events (
            id INTEGER PRIMARY KEY, kind TEXT NOT NULL, scope TEXT NOT NULL,
            capability TEXT NOT NULL, value_json TEXT NOT NULL,
            reason TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (datetime('now')));
        CREATE TABLE IF NOT EXISTS patrol_observations (
            scope TEXT NOT NULL, path TEXT NOT NULL, signature TEXT NOT NULL,
            evidence_json TEXT NOT NULL, last_run_id INTEGER,
            PRIMARY KEY(scope, path));
        CREATE TABLE IF NOT EXISTS proposal_supersessions (
            proposal_id INTEGER PRIMARY KEY, previous_status TEXT NOT NULL,
            reason TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (datetime('now')));
    """)


def record_policy(conn, *, kind, scope, capability="*", value, reason):
    if not reason.strip():
        raise ValueError("A policy change needs an explicit reason.")
    if kind == "lifecycle" and value not in LIFECYCLES:
        raise ValueError("Unknown lifecycle")
    if kind == "authority":
        if value.get("permission") not in PERMISSIONS:
            raise ValueError("Unknown permission")
        if capability == "*" and value["permission"] != "ASK":
            raise ValueError("Standing grants must name a capability")
        if value["permission"] != "ASK" and not value.get("constraints"):
            raise ValueError("Standing grants require bounded conditions")
    if kind not in {"lifecycle", "authority", "attention"}:
        raise ValueError("Unknown policy kind")
    if kind == "attention" and value not in ATTENTION:
        raise ValueError("Unknown attention posture")
    initialize_patrol(conn)
    cur = conn.execute("INSERT INTO patrol_policy_events(kind,scope,capability,value_json,reason) VALUES(?,?,?,?,?)",
                       (kind, scope, capability, json.dumps(value), reason))
    conn.commit()
    return cur.lastrowid


def scoped_policy(conn, scope, kind, capability="*"):
    initialize_patrol(conn)
    rows = conn.execute("SELECT * FROM patrol_policy_events WHERE kind=? ORDER BY id DESC", (kind,)).fetchall()
    matches = [r for r in rows if _is_under(scope, r["scope"]) and r["capability"] in {capability, "*"}]
    matches.sort(key=lambda r: (len(r["scope"].rstrip("\\/")), r["id"]), reverse=True)
    if matches:
        row = matches[0]
        return {"value": json.loads(row["value_json"]), "version": row["id"], "scope": row["scope"]}
    default = {"lifecycle": "CONSTRUCTION", "attention": "SILENT", "authority": {"permission": "ASK"}}[kind]
    return {"value": default, "version": 0, "scope": scope}


def check_authority(conn, scope, capability, conditions, *, shadow=True):
    policy = scoped_policy(conn, scope, "authority", capability)
    grant = policy["value"]
    permission = grant.get("permission", "ASK")
    reason = "No standing permission" if permission == "ASK" else "Explicit grant within its conditions"
    if shadow and conditions.get("managed_mutation"):
        permission, reason = "ASK", "Shadow authority cannot mutate managed files"
    elif permission == "OBSERVE" and conditions.get("managed_mutation"):
        permission, reason = "ASK", "OBSERVE does not authorize managed mutations"
    elif permission != "ASK" and "managed_mutation" not in conditions:
        permission, reason = "ASK", "Mutation conditions were not established"
    elif permission != "ASK":
        for key, bound in grant.get("constraints", {}).items():
            actual = conditions.get(key)
            if actual is None or (actual > bound if type(bound) in (int, float) else actual != bound):
                permission, reason = "ASK", f"Conditions exceed or do not establish {key}"
                break
    return {"permission": permission, "policy_version": policy["version"], "reason": reason}


def minimum_organization(group_count, parent_count, *, demonstrated_utility=False, operational_requirement=False):
    if group_count < 0 or parent_count < group_count:
        raise ValueError("Invalid group/parent counts")
    eligible = group_count >= 5 and parent_count - group_count >= 15
    return {"eligible": eligible or operational_requirement,
            "recommend_subfolder": operational_requirement or (eligible and demonstrated_utility),
            "default": "metadata", "operational_override": operational_requirement}


def live_discover(scope, *, max_files=500, max_entries=10000, max_seconds=15, max_depth=20):
    """Never follow symlinks/junctions; report incomplete coverage explicitly."""
    if any(type(value) is not int or value <= 0 for value in (max_files, max_entries)):
        raise ValueError('Positive integer discovery count budgets required')
    if type(max_depth) is not int or max_depth < 0:
        raise ValueError('A nonnegative integer discovery depth is required')
    try:
        valid_time = type(max_seconds) in (int, float) and math.isfinite(max_seconds) and max_seconds > 0
    except OverflowError:
        valid_time = False
    if not valid_time:
        raise ValueError('A finite positive discovery time budget is required')
    from core.read_guard import require_path_not_held
    started = time.monotonic()
    rows, errors, skipped = [], [], []
    visited = 0
    bounded = False
    def walk(path, depth):
        nonlocal visited, bounded
        if depth > max_depth:
            bounded = True
            return
        try:
            require_path_not_held(path)
            metadata = os.lstat(path)
            if stat.S_ISLNK(metadata.st_mode) or getattr(metadata, "st_file_attributes", 0) & 0x400:
                skipped.append({"path": str(path), "reason": "reparse_point"})
                return
            if stat.S_ISREG(metadata.st_mode):
                rows.append({"canonical_path": str(path), "hash": None, "size_bytes": metadata.st_size,
                             "modified_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(metadata.st_mtime)),
                             "mtime_ns": metadata.st_mtime_ns, "evidence_source": "live_scan"})
                return
            if not stat.S_ISDIR(metadata.st_mode):
                return
            require_path_not_held(path)
            with os.scandir(path) as entries:
                while True:
                    if len(rows) >= max_files or visited >= max_entries or time.monotonic() - started >= max_seconds:
                        bounded = True
                        break
                    require_path_not_held(path)
                    try:
                        entry = next(entries)
                    except StopIteration:
                        break
                    visited += 1
                    walk(Path(entry.path), depth + 1)
        except OSError as exc:
            errors.append({"path": str(path), "error": str(exc)})
    # A reparse ancestor is just as unsafe as a reparse leaf.
    try:
        require_path_not_held(scope)
        candidate = Path(scope).absolute()
        for ancestor in candidate.parents:
            require_path_not_held(candidate)
            require_path_not_held(ancestor)
            info = os.lstat(ancestor)
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                return [], {"complete": False, "errors": [], "skipped": [{"path": str(ancestor), "reason": "reparse_ancestor"}], "entries": 0}
    except OSError as exc:
        return [], {"complete": False, "errors": [{"path": scope, "error": str(exc)}], "skipped": [], "entries": 0}
    walk(candidate, 0)
    rows.sort(key=lambda r: r["canonical_path"].casefold())
    return rows, {"complete": not (bounded or errors or skipped), "budget_exhausted": bounded,
                  "errors": errors, "skipped": skipped, "entries": visited}


def supersede_portal_proposals(conn):
    initialize_patrol(conn)
    rows = conn.execute("SELECT id,status FROM proposals WHERE status IN ('pending','approved') AND description LIKE 'Suggest grouping %project-portal reference%'").fetchall()
    for row in rows:
        conn.execute("INSERT OR IGNORE INTO proposal_supersessions(proposal_id,previous_status,reason) VALUES(?,?,?)",
                     (row["id"], row["status"], "Retired mass shortcut semantics; regenerate through Shadow resolution"))
        conn.execute("UPDATE proposals SET status='superseded',resolved_at=datetime('now') WHERE id=?", (row["id"],))
    conn.commit()
    return [r["id"] for r in rows]


def compare_observations(conn, scope, run_id, observations, *, complete):
    previous = {r["path"]: r["signature"] for r in conn.execute("SELECT path,signature FROM patrol_observations WHERE scope=?", (scope,))}
    added, changed = [], []
    current = set()
    for evidence in observations:
        path = evidence["path"]
        current.add(path)
        signature = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
        if path not in previous:
            added.append(path)
        elif previous[path] != signature:
            changed.append(path)
        conn.execute("INSERT OR REPLACE INTO patrol_observations VALUES(?,?,?,?,?)", (scope,path,signature,json.dumps(evidence),run_id))
    missing = sorted(set(previous) - current) if complete else []
    if complete:
        for path in missing:
            conn.execute("DELETE FROM patrol_observations WHERE scope=? AND path=?", (scope,path))
    conn.commit()
    return {"added": added, "changed": changed, "not_observed": missing,
            "absence_inferred": complete, "unchanged": len(current) - len(added) - len(changed)}
