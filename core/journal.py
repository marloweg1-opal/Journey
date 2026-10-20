"""
Mini ARK operation journal.

Per Amendment 1: every mutating operation follows
    Preview -> Transaction -> Journal -> Verification -> Undo window

This module exists BEFORE any real mutating operations do (Phase 6+
project portals, shortcuts, etc.). The framework is built now so that
when mutation capability arrives, it has nowhere to go but through this
gate -- there is no code path for a future feature to "forget" to log
itself.

Undo is itself a transaction, never history erasure. Reversing OP-142
creates OP-143; OP-142's record stays intact and is marked reversed.
"""

import json
import sys
from pathlib import Path

KILL_SWITCH_FLAG = Path(__file__).parent.parent / "ARK_EXECUTION_DISABLED.flag"


class ExecutionDisabled(Exception):
    """Raised when the external kill-switch flag is present."""
    pass


class UndoConflict(Exception):
    """Current reality conflicts with historical undo authority."""
    def __init__(self, evidence):
        self.evidence = evidence
        super().__init__(evidence['reason'])


def record_recovery(conn, op_id, state, evidence):
    conn.execute('''CREATE TABLE IF NOT EXISTS operation_recovery_events (
        id INTEGER PRIMARY KEY, operation_id INTEGER NOT NULL, state TEXT NOT NULL,
        evidence_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (datetime('now')))''')
    conn.execute('INSERT INTO operation_recovery_events(operation_id,state,evidence_json) VALUES(?,?,?)',
                 (op_id, state, json.dumps(evidence)))


def check_kill_switch():
    """
    Hard external stop, per Amendment 1: 'the authority to stop Mini ARK
    lives outside Mini ARK.' This does not depend on the Mini ARK process
    cooperating -- it's a file-existence check that runs before any
    mutating action, and Mini ARK cannot remove this flag itself.
    """
    if KILL_SWITCH_FLAG.exists():
        raise ExecutionDisabled(
            f"[BLOCKED] {KILL_SWITCH_FLAG.name} is present. "
            "Mini ARK may observe/report but cannot execute mutations. "
            "Remove the flag file manually to resume."
        )


def preview_operation(conn, action_type: str, tier: int, target_path: str,
                       planned_changes: dict) -> dict:
    """
    Step 1: PREVIEW. Nothing happens to real files here. This just shows
    what WOULD happen and returns a preview object for the user/caller
    to approve or reject.
    """
    print(f"MINI ARK PROPOSED OPERATION")
    print(f"  Action:       {action_type}")
    print(f"  Tier:         {tier}")
    print(f"  Target:       {target_path}")
    for k, v in planned_changes.items():
        print(f"  {k}: {v}")
    print(f"  [PREVIEW ONLY -- nothing has been changed]")
    return {
        "action_type": action_type,
        "tier": tier,
        "target_path": target_path,
        "planned_changes": planned_changes,
    }


def begin_transaction(conn, preview: dict, previous_state: dict, *, proposal_item_id=None) -> int:
    """
    Step 2/3: TRANSACTION + JOURNAL. Records the before-state BEFORE
    performing the action. If this row doesn't exist, the action must
    not proceed -- journaling is not optional or after-the-fact.
    """
    check_kill_switch()
    previous_state = {**previous_state, "planned_changes": preview["planned_changes"]}
    cur = conn.execute(
        """INSERT INTO action_log (action_type, tier, target_path, previous_state, status)
           VALUES (?, ?, ?, ?, 'running');""",
        (preview["action_type"], preview["tier"], preview["target_path"],
         json.dumps(previous_state)),
    )
    if proposal_item_id is not None:
        claimed = conn.execute("""UPDATE proposal_items SET action_log_id=?
            WHERE id=? AND status='pending' AND action_log_id IS NULL
            AND proposal_id IN (SELECT id FROM proposals WHERE status='approved')""",
            (cur.lastrowid, proposal_item_id))
        if claimed.rowcount != 1:
            conn.rollback()
            raise ValueError('Proposal item changed or was already claimed; no filesystem action permitted')
    conn.commit()
    return cur.lastrowid


def complete_operation(conn, op_id: int, new_state: dict, verified: bool) -> dict:
    """
    Step 4: VERIFICATION. The caller performed the actual filesystem
    action and confirms whether the resulting state matches what was
    expected. This does not re-derive trust -- it records the claim,
    with the caller responsible for having actually checked.
    """
    if type(verified) is not bool or not isinstance(new_state, dict):
        raise ValueError('Completion requires an explicit boolean and structured evidence')
    cur = conn.execute(
        "UPDATE action_log SET new_state = ?, status=? WHERE id = ? AND status='running';",
        (json.dumps(new_state), "applied" if verified else "manual_recovery_required", op_id),
    )
    if cur.rowcount != 1:
        conn.rollback()
        raise ValueError('Completion cannot overwrite a non-running or missing receipt')
    conn.commit()

    status = "COMPLETE" if verified else "COMPLETE (unverified)"
    from core.recovery_inspection import inspect_operation
    undo_state = inspect_operation(conn, op_id)['state']
    print(f"{'OK' if verified else 'WARNING'} {status}")
    print(f"  Operation ID: OP-{op_id:06d}")
    print(f"  Undo state: {undo_state}")
    if undo_state == 'UNDO_AVAILABLE':
        print(f"  To reverse: ark undo OP-{op_id:06d}")
    return {"op_id": op_id, "verified": verified, 'undo_state':undo_state}


def undo_operation(conn, op_id: int, undo_fn) -> dict:
    """
    Step 5: UNDO. Creates a NEW action_log row that reverses the old one.
    The original row is marked reversed but never deleted -- the
    historical record stays intact, per Amendment 1.

    undo_fn: caller-supplied function that actually performs the reverse
    filesystem operation, given the original's previous_state.
    """
    check_kill_switch()
    row = conn.execute("SELECT * FROM action_log WHERE id = ?;", (op_id,)).fetchone()
    if row is None:
        print(f"[FAILED] No such operation: OP-{op_id:06d}")
        return {"status": "failed", "reason": "not_found"}
    if row["status"] == "reversed":
        print(f"[WARNING] OP-{op_id:06d} was already reversed.")
        return {"status": "already_reversed"}
    if row["status"] != "applied":
        return {"status": "failed", "reason": "operation_requires_recovery_before_undo"}

    try:
        previous_state = json.loads(row["previous_state"])
        if not isinstance(previous_state, dict):
            raise ValueError('Previous state must be an object')
    except (ValueError, TypeError) as exc:
        evidence = {'reason':str(exc), 'physical_changes':False}
        conn.execute("UPDATE action_log SET status='manual_recovery_required' WHERE id=?", (op_id,))
        record_recovery(conn, op_id, 'MANUAL_RECOVERY_REQUIRED', evidence)
        conn.commit()
        return {'status':'MANUAL_RECOVERY_REQUIRED', 'evidence':evidence}
    # Claim the original and commit reversal intent before touching files.
    claimed = conn.execute("UPDATE action_log SET status='reversing' WHERE id=? AND status='applied'", (op_id,))
    if claimed.rowcount != 1:
        conn.rollback()
        return {"status": "failed", "reason": "operation_requires_recovery_before_undo"}
    cur = conn.execute(
        """INSERT INTO action_log (action_type, tier, target_path, previous_state, new_state, status)
           VALUES (?, ?, ?, ?, ?, 'running');""",
        (f"undo:{row['action_type']}", row["tier"], row["target_path"],
         row["new_state"], row["previous_state"]),
    )
    new_op_id = cur.lastrowid
    conn.commit()
    try:
        undo_fn(previous_state)
    except UndoConflict as exc:
        conn.execute("UPDATE action_log SET status='undo_blocked_by_drift' WHERE id=?", (op_id,))
        conn.execute("UPDATE action_log SET status='undo_requires_review' WHERE id=?", (new_op_id,))
        record_recovery(conn, op_id, 'UNDO_BLOCKED_BY_DRIFT', {**exc.evidence, 'reversal_op_id': new_op_id})
        conn.commit()
        return {'status': 'UNDO_BLOCKED_BY_DRIFT', 'reversal_op_id': new_op_id, 'evidence': exc.evidence}
    except BaseException as exc:
        conn.execute("UPDATE action_log SET status='manual_recovery_required' WHERE id IN (?,?)", (op_id, new_op_id))
        record_recovery(conn, op_id, 'MANUAL_RECOVERY_REQUIRED', {'error': str(exc), 'reversal_op_id': new_op_id,
                         'physical_outcome': 'UNKNOWN; inspect before retrying'})
        conn.commit()
        raise

    conn.execute("UPDATE action_log SET status='applied' WHERE id=?", (new_op_id,))
    record_recovery(conn, op_id, 'UNDO_COMPLETED', {'reversal_op_id': new_op_id})
    conn.execute(
        "UPDATE action_log SET status = 'reversed', reversed_at = datetime('now') WHERE id = ?;",
        (op_id,),
    )
    conn.commit()

    print(f"[SUCCESS] OP-{op_id:06d} reversed via OP-{new_op_id:06d}")
    print(f"  Original operation record preserved, marked reversed.")
    return {"status": "reversed", "reversal_op_id": new_op_id}
