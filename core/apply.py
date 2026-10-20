"""
Mini ARK apply — the ONLY module allowed to actually touch a file's
real location. Everything upstream (organizer.py) proposes; this
module is where a proposal, once approved, becomes real filesystem
change.

Per Amendment 1, every item here walks:
    Preview -> Transaction -> Journal -> Verification -> Undo window

Two possible outcomes per file, decided PER ITEM, not per proposal:
  - 'shortcut': original file never moves. A Windows directory
    junction/symlink is created at dest_path pointing at the real file.
    Fully non-destructive; undo just removes the shortcut.
  - 'move': the file is physically relocated. canonical_path in the
    files table is updated to match. This is the destructive path and
    is the one this module is most defensive about.

Safety order, enforced before ANY disk write, in this sequence:
  1. Protected path check (hard floor, not just DB-editable)
  2. Dependent check (known dependencies block the move; approval does
     not silently change into permission to create a shortcut).
  3. Circuit breaker (batch magnitude, independent of tier)
  4. Kill switch (checked again at the actual transaction boundary,
     inside journal.begin_transaction -- this module does not bypass it)
"""

import os
import json
import platform
import shutil
from dataclasses import asdict
from pathlib import Path

from core import journal
from core.recovery_inspection import file_identity
from core import quarantine
from core.action_evidence import quarantine_hold
from core.move_evidence import checked_evidence, MoveEvidenceDenied
from core.circuit_breaker import check_operation_magnitude, OperationTooLarge

# Non-negotiable floor. Editable rows in protected_paths can ADD to
# this set; nothing can remove from it, because it isn't read from
# the database at all.
_HARDCODED_PROTECTED_PREFIXES = [
    r"C:\Windows",
    r"C:\Program Files\WindowsApps",
    r"C:\Program Files\Common Files",
    r"C:\ProgramData\Microsoft",
    r"C:\$Recycle.Bin",
    r"C:\System Volume Information",
]


class ProposalNotApproved(Exception):
    pass


# ---------------------------------------------------------------------
# Dependent tracking
# ---------------------------------------------------------------------

def register_dependent(conn, canonical_path: str, program_name: str,
                        reference_location: str = None,
                        reference_context: str = None) -> int:
    """
    Manually declare that some program depends on a path -- e.g.
    "Rainmeter reads M:\\Assets\\clock.png from skin.ini line 14".
    This is the ground truth apply() checks; an unregistered dependent
    is invisible to Mini ARK on purpose (no silent trust, no guessing).
    """
    cur = conn.execute(
        """INSERT INTO file_dependents
           (canonical_path, program_name, reference_location, reference_context)
           VALUES (?, ?, ?, ?);""",
        (canonical_path, program_name, reference_location, reference_context),
    )
    conn.commit()
    return cur.lastrowid


def scan_config_for_dependents(conn, config_path: str, program_name: str,
                                 candidate_paths: list) -> dict:
    """
    Plain-text scan of a config file (Rainmeter .ini, or any text-based
    config CareBloomOS/Welfare Witchcraft use) for literal references
    to any path in candidate_paths. Registers a dependent row for each
    hit found. This is intentionally simple (substring match per line)
    rather than format-aware -- extend per-program if a config format
    needs smarter parsing later.
    """
    config_file = Path(config_path)
    if not config_file.exists():
        return {"status": "failed", "reason": "config_not_found"}

    found = []
    with open(config_file, "r", encoding="utf-8", errors="ignore") as f:
        for line_no, line in enumerate(f, start=1):
            for candidate in candidate_paths:
                if candidate.lower() in line.lower():
                    register_dependent(
                        conn, candidate, program_name,
                        reference_location=f"{config_path}:{line_no}",
                        reference_context=line.strip(),
                    )
                    found.append({"path": candidate, "line": line_no, "context": line.strip()})

    return {"status": "scanned", "config": config_path, "dependents_found": found}


def get_active_dependents(conn, canonical_path: str) -> list:
    rows = conn.execute(
        "SELECT * FROM file_dependents WHERE canonical_path = ? AND status = 'active';",
        (canonical_path,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------
# Protection
# ---------------------------------------------------------------------

def is_protected(conn, path: str) -> str:
    """Returns a reason string if protected, None if not. Checks the
    hardcoded floor FIRST, then extends with any DB rows. Prefix-based,
    so anything nested under a reserved folder inherits the same
    protection automatically -- no separate ancestor bookkeeping needed."""
    norm = str(Path(path))
    for prefix in _HARDCODED_PROTECTED_PREFIXES:
        if norm.lower().startswith(prefix.lower()):
            return f"Hardcoded system-critical path: {prefix}"

    rows = conn.execute("SELECT path_prefix, reason FROM protected_paths;").fetchall()
    for row in rows:
        if norm.lower().startswith(row["path_prefix"].lower()):
            return row["reason"] or f"Protected path: {row['path_prefix']}"

    return None


def add_reservation(conn, path: str, reason: str = None) -> int:
    """
    Marks a folder (and everything under it) off-limits to Mini ARK --
    find-empty will never flag it or anything above it as a dead end,
    and apply() will never move/shortcut/quarantine it. For scaffolding
    you've deliberately built ahead of populating it.
    """
    norm = str(Path(path))
    cur = conn.execute(
        """INSERT INTO protected_paths (path_prefix, reason, category)
           VALUES (?, ?, 'user_reserved')
           ON CONFLICT(path_prefix) DO UPDATE SET reason=excluded.reason;""",
        (norm, reason or "Reserved by user"),
    )
    conn.commit()
    return cur.lastrowid


def remove_reservation(conn, path: str) -> dict:
    """Un-reserves a path. Only affects DB-backed reservations -- the
    hardcoded system floor cannot be removed this way, by design."""
    norm = str(Path(path))
    for prefix in _HARDCODED_PROTECTED_PREFIXES:
        if norm.lower() == prefix.lower():
            return {"status": "failed", "reason": "cannot unreserve a hardcoded system-floor path"}
    cur = conn.execute("DELETE FROM protected_paths WHERE path_prefix = ?;", (norm,))
    conn.commit()
    return {"status": "removed" if cur.rowcount else "not_found"}


def list_reservations(conn) -> list:
    rows = conn.execute(
        "SELECT path_prefix, reason, category FROM protected_paths ORDER BY category, path_prefix;"
    ).fetchall()
    hardcoded = [{"path_prefix": p, "reason": "Hardcoded system floor", "category": "system_floor"}
                 for p in _HARDCODED_PROTECTED_PREFIXES]
    return hardcoded + [dict(r) for r in rows]


def skip_item(conn, item_id: int, reason: str = "user declined") -> dict:
    """Marks a single proposal_item as skipped so plan_apply/execute_apply
    never act on it, without affecting sibling items in the same proposal.
    This is the itemized 'choose which ones' mechanism -- review with
    list_proposal_items, skip what you don't want, apply the rest."""
    row = conn.execute("SELECT id FROM proposal_items WHERE id = ?;", (item_id,)).fetchone()
    if row is None:
        return {"status": "failed", "reason": "not_found"}
    conn.execute(
        "UPDATE proposal_items SET status='skipped', block_reason=? WHERE id=?;",
        (reason, item_id),
    )
    conn.commit()
    return {"status": "skipped", "item_id": item_id}


def list_proposal_items(conn, proposal_id: int) -> list:
    rows = conn.execute(
        "SELECT id, canonical_path, dest_path, requested_mode, status, block_reason "
        "FROM proposal_items WHERE proposal_id = ? ORDER BY id;",
        (proposal_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------
# Resolve a proposal into concrete per-file rows
# ---------------------------------------------------------------------

def add_proposal_item(conn, proposal_id: int, canonical_path: str,
                       dest_path: str = None, requested_mode: str = "shortcut") -> int:
    if requested_mode not in ("move", "shortcut", "quarantine"):
        raise ValueError("requested_mode must be 'move', 'shortcut', or 'quarantine'")
    if requested_mode != "quarantine" and dest_path is None:
        raise ValueError("dest_path is required for 'move' and 'shortcut' modes")
    cur = conn.execute(
        """INSERT INTO proposal_items
           (proposal_id, canonical_path, dest_path, requested_mode)
           VALUES (?, ?, ?, ?);""",
        (proposal_id, canonical_path, dest_path, requested_mode),
    )
    conn.commit()
    return cur.lastrowid


# ---------------------------------------------------------------------
# PREVIEW: build the plan, decide real mode per item, no disk writes
# ---------------------------------------------------------------------

def move_evidence_hold():
    """No production adapter can yet authenticate complete move/dependency evidence."""
    return ('MOVE_EVIDENCE_REQUIRED: No trusted move evidence verifier is available. '
            'Approval and absence of registered dependents do not prove dependency clearance.')


def plan_apply(conn, proposal_id: int, *, move_verifier=None) -> dict:
    """
    Step 1 of the ritual. Walks every pending proposal_item under this
    proposal, resolves protected/dependent status, and decides the
    ACTUAL mode per item. Writes nothing to disk. Writes a
    code_change_needed proposal for any item downgraded due to
    dependents, so the report exists whether or not the human proceeds.
    """
    proposal = conn.execute("SELECT * FROM proposals WHERE id = ?;", (proposal_id,)).fetchone()
    if proposal is None:
        return {"status": "failed", "reason": "proposal_not_found"}
    if proposal["status"] != "approved":
        raise ProposalNotApproved(
            f"Proposal {proposal_id} has status '{proposal['status']}', not 'approved'. "
            f"Approve it explicitly before planning apply."
        )

    items = conn.execute(
        "SELECT * FROM proposal_items WHERE proposal_id = ? AND status = 'pending';",
        (proposal_id,),
    ).fetchall()

    plan = []
    downgrade_report_lines = []

    for item in items:
        reason = is_protected(conn, item["canonical_path"])
        if reason:
            plan.append({"item_id": item["id"], "path": item["canonical_path"],
                         "action": "blocked", "reason": reason})
            continue

        actual_mode = item["requested_mode"]

        evidence_reason = None
        if actual_mode == 'move':
            try:
                if move_verifier is None:
                    evidence_reason = move_evidence_hold()
                else:
                    checked_evidence(move_verifier, conn, item, phase='plan')
            except MoveEvidenceDenied as exc:
                evidence_reason = str(exc)
        if evidence_reason:
            plan.append({'item_id': item['id'], 'path': item['canonical_path'],
                         'action': 'blocked', 'reason': evidence_reason})
            continue

        if actual_mode == "move":
            dependents = get_active_dependents(conn, item["canonical_path"])
            if dependents:
                plan.append({"item_id": item["id"], "path": item["canonical_path"],
                             "action": "blocked", "reason": "Active dependencies require a new reviewed resolution; move approval does not authorize a shortcut."})
                lines = [f"  - {d['program_name']} references this at "
                         f"{d['reference_location']}: \"{d['reference_context']}\""
                         for d in dependents]
                downgrade_report_lines.append(
                    f"{item['canonical_path']} -> {item['dest_path']}:\n" + "\n".join(lines)
                )
                continue

        elif actual_mode == "quarantine":
            plan.append({"item_id": item["id"], "path": item["canonical_path"],
                         "action": "blocked", "reason": quarantine_hold()})
            continue

        plan.append({"item_id": item["id"], "path": item["canonical_path"],
                     "dest": item["dest_path"], "action": actual_mode})

    if downgrade_report_lines:
        report_body = (
            "The following files were requested as real MOVES but have known "
            "dependents, so they were blocked without changing the approved semantics. "
            "To actually relocate them, update the referencing config(s) first, "
            "then re-request the move:\n\n" + "\n\n".join(downgrade_report_lines)
        )
        conn.execute(
            """INSERT INTO proposals (description, project_id, severity, status)
               VALUES (?, ?, 'decision', 'pending');""",
            (report_body, proposal["project_id"]),
        )
        conn.commit()

    blocked = [p for p in plan if p["action"] == "blocked"]
    movable = [p for p in plan if p["action"] in ("move", "shortcut", "quarantine")]

    return {
        "status": "planned",
        "proposal_id": proposal_id,
        "total_items": len(plan),
        "blocked_count": len(blocked),
        "blocked": blocked,
        "to_apply": movable,
        "downgraded_count": len(downgrade_report_lines),
        "note": "PREVIEW ONLY. Nothing on disk has changed. Call execute_apply(plan) to proceed.",
    }


# ---------------------------------------------------------------------
# EXECUTE: the real filesystem mutation, one item at a time, journaled
# ---------------------------------------------------------------------

def _create_shortcut(source: Path, dest: Path):
    """Windows directory junction / symlink. Original file untouched."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if platform.system() == "Windows":
        if source.is_dir():
            os.system(f'mklink /J "{dest}" "{source}"')
        else:
            os.system(f'mklink "{dest}" "{source}"')
    else:
        os.symlink(source, dest)


def _remove_shortcut(dest: Path):
    """Undo helper for a shortcut. Windows junctions report is_dir()=True
    but are not real directories -- rmdir on a junction removes just the
    link, never touching the real target's contents. Plain symlinks
    (non-Windows, or file-level Windows symlinks) use unlink instead."""
    if dest.is_symlink():
        dest.unlink()
    elif dest.is_dir():
        os.rmdir(dest)


def _move_no_replace(source, dest):
    """Never fall back to copy/delete or nest into an occupied directory."""
    if platform.system() != 'Windows':
        raise RuntimeError('No verified no-replace move primitive on this platform')
    os.rename(source, dest)


def execute_apply(conn, plan: dict, tier: int = 3, verbose: bool = True, *, move_verifier=None) -> dict:
    """
    Step 2-4 of the ritual, run per item: Transaction -> real filesystem
    action -> Verification. Circuit breaker checked ONCE against the
    whole batch before any item executes. Kill switch checked again
    inside journal.begin_transaction per item (not bypassable).
    """
    to_apply = plan.get("to_apply", [])
    if not to_apply:
        return {"status": "no_items", "message": "Nothing in this plan is eligible to apply."}

    total_scope = conn.execute("SELECT COUNT(*) as c FROM files WHERE status='present';").fetchone()["c"]
    try:
        check_operation_magnitude(len(to_apply), total_items_in_scope=total_scope,
                                    operation_label="apply")
    except OperationTooLarge as e:
        return {"status": "blocked_by_circuit_breaker", "reason": str(e)}

    applied, failed = [], []

    for entry in to_apply:
        item = conn.execute("SELECT * FROM proposal_items WHERE id = ?;", (entry["item_id"],)).fetchone()
        if item is None:
            failed.append({"path": None, "reason": "Proposal item no longer exists"})
            continue
        proposal = conn.execute("SELECT status FROM proposals WHERE id=?", (item["proposal_id"],)).fetchone()
        if item['action_log_id'] is not None:
            failed.append({'path': item['canonical_path'], 'reason': 'Prior execution receipt exists; inspect recovery before retrying'})
            continue
        if not proposal or proposal["status"] != "approved" or item["status"] != "pending" or entry["action"] != item["requested_mode"]:
            failed.append({"path": item["canonical_path"], "reason": "Approval or item semantics changed; fresh review required"})
            continue
        evidence = None
        evidence_reason = None
        if entry['action'] == 'move':
            try:
                if move_verifier is None:
                    evidence_reason = move_evidence_hold()
                else:
                    evidence = checked_evidence(move_verifier, conn, item, phase='execute')
            except MoveEvidenceDenied as exc:
                evidence_reason = str(exc)
        if evidence_reason:
            failed.append({'path': item['canonical_path'], 'reason': evidence_reason})
            continue
        source = Path(item["canonical_path"])
        dest = Path(item["dest_path"]) if item["dest_path"] else None
        action = entry["action"]
        if evidence is not None:
            try:
                from core.read_guard import require_path_not_held
                from core.media_inventory import safe_metadata
                require_path_not_held(source)
                require_path_not_held(dest)
                safe_metadata(source, read_guard=require_path_not_held)
                safe_metadata(dest.parent, read_guard=require_path_not_held)
                if is_protected(conn, str(dest)):
                    raise ValueError('Destination is protected')
            except (OSError, ValueError) as exc:
                failed.append({'path': str(source), 'reason': str(exc)})
                continue
        if dest is not None and os.path.lexists(dest):
            failed.append({'path': str(source), 'reason': 'Destination occupied; no overwrite or implicit directory nesting permitted'})
            continue
        protection = is_protected(conn, str(source))
        dependencies = get_active_dependents(conn, str(source))
        if protection or (dependencies and action in {"move", "quarantine"}):
            failed.append({"path": str(source), "reason": protection or "Active dependencies require fresh review"})
            continue
        if action == "quarantine":
            failed.append({"path": str(source), "reason": quarantine_hold()})
            continue

        identity = file_identity(source) if action == 'move' else None
        if evidence is not None and identity != asdict(evidence.identity):
            failed.append({'path': str(source), 'reason': 'Source no longer matches reviewed identity'})
            continue
        if action == 'move' and identity is None:
            failed.append({'path':str(source), 'reason':'Stable regular-file identity unavailable; move requires review'})
            continue

        if action == 'move':
            try:
                from core.media_inventory import safe_metadata
                parent = safe_metadata(dest.parent)
                source_now = safe_metadata(source)
                if platform.system() != 'Windows' or parent.st_dev != source_now.st_dev:
                    raise ValueError('Cross-volume or unsupported move requires staged recovery review')
                if not dest.parent.is_dir():
                    raise ValueError('Existing destination directory required; no implicit folder creation')
            except (OSError, ValueError) as exc:
                failed.append({'path':str(source), 'reason':str(exc)})
                continue

        preview = journal.preview_operation(
            conn, action_type=f"file_{action}", tier=tier, target_path=str(source),
            planned_changes={"dest": str(dest) if dest else "(quarantine -- destination assigned at apply time)"},
        )

        try:
            if evidence is not None:
                if checked_evidence(move_verifier, conn, item, phase='before_intent') != evidence:
                    raise MoveEvidenceDenied('Evidence changed before intent')
            op_id = journal.begin_transaction(
                conn, preview, previous_state={"path": str(source), "existed": source.exists(), 'identity':identity,
                                               'move_evidence': asdict(evidence) if evidence is not None else None},
                proposal_item_id=item['id'],
            )
        except MoveEvidenceDenied as exc:
            failed.append({'path': str(source), 'reason': str(exc)})
            continue
        except journal.ExecutionDisabled as e:
            return {"status": "blocked_by_kill_switch", "reason": str(e),
                    "applied_before_block": applied, "failed": failed}

        try:
            journal.check_kill_switch()
            if action == "shortcut":
                _create_shortcut(source, dest)
                verified = dest.exists() and source.exists()
            elif action == "move":
                if evidence is not None:
                    if checked_evidence(move_verifier, conn, item, phase='before_mutation') != evidence:
                        raise MoveEvidenceDenied('Evidence changed after intent')
                    require_path_not_held(source)
                    require_path_not_held(dest)
                    safe_metadata(dest.parent, read_guard=require_path_not_held)
                    if is_protected(conn, str(source)) or is_protected(conn, str(dest)) or get_active_dependents(conn, str(source)):
                        raise MoveEvidenceDenied('Protection or dependencies changed after intent')
                if file_identity(source) != identity:
                    raise RuntimeError('Source changed after intent; move stopped')
                _move_no_replace(source, dest)
                conn.execute("UPDATE files SET canonical_path = ? WHERE canonical_path = ?;",
                             (str(dest), str(source)))
                verified = dest.exists() and not source.exists()
            else:  # quarantine
                q_result = quarantine.quarantine_item(conn, str(source), op_id)
                if q_result["status"] != "quarantined":
                    raise RuntimeError(q_result.get("reason", "quarantine failed"))
                dest = Path(q_result["quarantined_path"])
                conn.execute(
                    "UPDATE proposal_items SET dest_path = ? WHERE id = ?;",
                    (str(dest), item["id"]),
                )
                verified = dest.exists() and not source.exists()

            destination_identity = file_identity(dest) if action == 'move' else None
            if action == 'move':
                verified = verified and destination_identity is not None and destination_identity['sha256'] == identity['sha256']
            journal.complete_operation(conn, op_id, new_state={"path": str(dest), 'identity':destination_identity}, verified=verified)
            if not verified:
                raise RuntimeError("Filesystem result did not verify; manual recovery required")
            conn.execute(
                "UPDATE proposal_items SET status='applied', resolved_mode=?, action_log_id=?, resolved_at=datetime('now') WHERE id=?;",
                (action, op_id, item["id"]),
            )
            conn.commit()
            applied.append({"path": str(source), "dest": str(dest), "action": action, "op_id": op_id})
            if verbose:
                print(f"[APPLIED] {action}: {source} -> {dest}")

        except Exception as e:
            conn.execute("UPDATE action_log SET status='manual_recovery_required', new_state=? WHERE id=?",
                         (json.dumps({"path":str(dest) if dest else None,"error":str(e)}),op_id))
            conn.execute(
                "UPDATE proposal_items SET status='blocked', block_reason=? WHERE id=?;",
                (f"{type(e).__name__}: {e}", item["id"]),
            )
            conn.commit()
            failed.append({"path": str(source), "reason": str(e)})
            if verbose:
                print(f"[FAILED] {action}: {source} -- {e}")

    return {
        "status": "complete",
        "applied_count": len(applied),
        "failed_count": len(failed),
        "applied": applied,
        "failed": failed,
    }


# ---------------------------------------------------------------------
# UNDO: Step 5 of the ritual, for actions this module performed
# ---------------------------------------------------------------------

def undo_apply(conn, op_id: int) -> dict:
    """
    Consult recorded intent and current identity. Historical permission
    does not authorize overwriting a new occupant or undoing content drift.
    """
    row = conn.execute("SELECT * FROM action_log WHERE id = ?;", (op_id,)).fetchone()
    if row is None:
        return {"status": "failed", "reason": "not_found"}

    action = row["action_type"]  # 'file_move' or 'file_shortcut'
    if action != 'file_move':
        evidence = {'reason':'No current identity-bound reversal contract for this operation type',
                    'action_type':action, 'physical_changes':False}
        journal.record_recovery(conn, op_id, 'UNDO_REQUIRES_REVIEW', evidence)
        conn.commit()
        return {'status':'UNDO_REQUIRES_REVIEW', 'evidence':evidence}

    def _reverse(previous_state: dict):
        import json as _json
        new_state = _json.loads(row["new_state"])
        original_path = Path(previous_state["path"])
        current_path = Path(new_state["path"])

        if action == "file_shortcut":
            _remove_shortcut(current_path)
        elif action == "file_move":
            if os.path.lexists(original_path):
                occupant = original_path.lstat()
                raise journal.UndoConflict({'reason': 'Original path is occupied; occupant was not modified',
                    'original_path': str(original_path), 'current_path': str(current_path),
                    'occupant': {'size': occupant.st_size, 'mtime_ns': occupant.st_mtime_ns,
                                 'inode': occupant.st_ino, 'mode': occupant.st_mode},
                    'physical_changes': False})
            if not current_path.exists():
                raise FileNotFoundError(f"Cannot undo move: {current_path} no longer exists.")
            if not new_state.get('identity') or file_identity(current_path) != new_state['identity']:
                raise journal.UndoConflict({'reason':'Moved object changed or lacks identity evidence; no automatic undo',
                    'original_path':str(original_path), 'current_path':str(current_path), 'physical_changes':False})
            if platform.system() != 'Windows':
                raise RuntimeError('No verified no-replace undo primitive on this platform')
            if not original_path.parent.is_dir():
                raise journal.UndoConflict({'reason':'Original parent is unavailable; no folders recreated automatically',
                    'original_path':str(original_path), 'current_path':str(current_path), 'physical_changes':False})
            # Windows rename refuses an occupied destination atomically. Cross-volume
            # undo is held rather than falling back to a potentially overwriting copy.
            try:
                os.rename(current_path, original_path)
            except FileExistsError:
                raise journal.UndoConflict({'reason':'Original path became occupied during undo; no overwrite',
                    'original_path':str(original_path), 'current_path':str(current_path), 'physical_changes':False})
            if file_identity(original_path) != new_state['identity'] or os.path.lexists(current_path):
                raise RuntimeError('Undo physical result could not be verified')
            conn.execute("UPDATE files SET canonical_path = ? WHERE canonical_path = ?;",
                         (str(original_path), str(current_path)))
            conn.commit()
        elif action == "file_quarantine":
            result = quarantine.restore_from_quarantine(str(current_path))
            if result["status"] != "restored":
                raise RuntimeError(f"Cannot undo quarantine: {result.get('reason', 'unknown error')}")

    return journal.undo_operation(conn, op_id, _reverse)
