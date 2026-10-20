"""
Mini ARK dedupe -- resolves duplicate canonical_path ROWS in the files
table. This is a database bookkeeping fix, not a file operation: it
never reads, writes, moves, or deletes anything on the real
filesystem, with exactly one exception -- a fresh, read-only
os.path.exists() check used to determine ground truth, because a
stored 'present'/'missing' status can itself be stale (that's the
whole reason duplicates accumulated in the first place).

Per HEXSEED R: doctrine Sec. 10 & 12: hashes establish identity,
filenames don't; when rows disagree on content, preserve both and
flag for review rather than guessing; every resolution must be
logged and reversible.

Two categories per duplicate group:
  - SAFE (all rows agree on hash+size): the rows are the same content,
    just duplicated bookkeeping from before canonical_path had a real
    UNIQUE constraint. These consolidate to one row automatically,
    with status set from a live disk check.
  - CONFLICT (rows disagree on hash+size despite the same path): two
    genuinely different pieces of content have occupied this exact
    path at different times. Never auto-resolved -- always left for
    manual review.
"""

import os
import json
from core import journal
from core.reconcile import _query_duplicate_groups


def resolve_duplicate_rows(conn, root_path: str = None, dry_run: bool = True, verbose: bool = True) -> dict:
    groups = _query_duplicate_groups(conn, root_path)

    resolved, conflicts, errors = [], [], []

    for g in groups:
        row_ids = [int(x) for x in g["row_ids"].split(",")]
        rows = conn.execute(
            f"SELECT * FROM files WHERE id IN ({','.join('?' * len(row_ids))});",
            row_ids,
        ).fetchall()
        rows = [dict(r) for r in rows]

        hashes = {(r["hash"], r["size_bytes"]) for r in rows}
        if len(hashes) != 1 or None in [h for h, s in hashes]:
            conflicts.append({
                "path": g["canonical_path"],
                "row_ids": row_ids,
                "reason": "rows disagree on hash+size, or a hash is missing -- not safe to auto-merge",
                "rows": rows,
            })
            continue

        path = g["canonical_path"]
        exists_now = os.path.exists(path)
        correct_status = "present" if exists_now else "missing"

        if dry_run:
            resolved.append({
                "path": path, "row_ids": row_ids, "row_count": len(rows),
                "would_keep_status": correct_status,
                "action": "DRY RUN -- no changes made",
            })
            continue

        try:
            preview = journal.preview_operation(
                conn, action_type="dedupe_row_merge", tier=3, target_path=path,
                planned_changes={"row_ids": row_ids, "resulting_status": correct_status},
            )
            op_id = journal.begin_transaction(
                conn, preview, previous_state={"rows": rows},
            )
        except journal.ExecutionDisabled as e:
            return {"status": "blocked_by_kill_switch", "reason": str(e),
                    "resolved_before_block": resolved, "conflicts": conflicts}

        survivor = max(rows, key=lambda r: r["id"])
        for r in rows:
            if r["id"] != survivor["id"]:
                conn.execute("DELETE FROM files WHERE id = ?;", (r["id"],))
        conn.execute(
            "UPDATE files SET status = ?, last_seen_at = datetime('now') WHERE id = ?;",
            (correct_status, survivor["id"]),
        )
        journal.complete_operation(
            conn, op_id,
            new_state={"surviving_row_id": survivor["id"], "status": correct_status},
            verified=True,
        )
        conn.commit()

        resolved.append({
            "path": path, "row_ids": row_ids, "row_count": len(rows),
            "surviving_row_id": survivor["id"], "final_status": correct_status,
            "op_id": op_id,
        })
        if verbose:
            print(f"  [RESOLVED] {path}  ({len(rows)} rows -> 1, status={correct_status})")

    return {
        "status": "complete" if not dry_run else "dry_run_complete",
        "groups_found": len(groups),
        "resolved_count": len(resolved),
        "resolved": resolved,
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
    }


def undo_dedupe(conn, op_id: int) -> dict:
    """Recreates whichever rows were deleted during a dedupe merge,
    exactly as they were recorded in the journal's previous_state
    snapshot -- full row data was captured, so this is an exact
    restoration, not a best-effort guess."""
    row = conn.execute("SELECT * FROM action_log WHERE id = ?;", (op_id,)).fetchone()
    if row is None:
        return {"status": "failed", "reason": "not_found"}

    def _reverse(previous_state: dict):
        original_rows = previous_state["rows"]
        new_state = json.loads(row["new_state"])
        survivor_id = new_state["surviving_row_id"]
        conn.execute("DELETE FROM files WHERE id = ?;", (survivor_id,))
        for r in original_rows:
            conn.execute(
                """INSERT INTO files (id, canonical_path, hash, size_bytes, modified_at,
                                       first_seen_at, last_seen_at, status, project_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);""",
                (r["id"], r["canonical_path"], r["hash"], r["size_bytes"], r["modified_at"],
                 r["first_seen_at"], r["last_seen_at"], r["status"], r["project_id"]),
            )
        conn.commit()

    return journal.undo_operation(conn, op_id, _reverse)
