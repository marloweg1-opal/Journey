"""
Mini ARK casefix -- resolves confirmed case-only path drift, as
identified by reconcile.analyze_symmetry(). This is a pure
bookkeeping correction: it deletes the STALE 'missing' row for a file
that is actually present under a differently-cased path. It never
touches a real file and never touches the correct 'present' row.

Runs as ONE journaled, undo-able operation per invocation (not one
journal entry per row -- with tens of thousands of uniform, confirmed
corrections, per-row journaling adds overhead without adding real
audit value). The full set of deleted rows is captured in the
journal's previous_state, so a complete restoration is always
possible via undo regardless.

Refuses to run at all if the underlying data isn't PURE case drift --
if any real moves or genuinely unmatched files are mixed in, this
stops and hands back to 'diagnose' rather than silently bulk-cleaning
past something that needed individual attention.
"""

from core import journal
from core.reconcile import analyze_symmetry
from scanner.scanner import normalize_path


def resolve_case_drift(conn, root_path: str = None, dry_run: bool = True, verbose: bool = True) -> dict:
    result = analyze_symmetry(conn, root_path=root_path, verbose=verbose)

    if result["real_move_count"] or result["unmatched_count"]:
        return {
            "status": "refused",
            "reason": (
                f"{result['real_move_count']} real move(s) and "
                f"{result['unmatched_count']} unmatched item(s) are also present -- "
                f"only pure case-drift is safe to bulk-resolve automatically. "
                f"Review those separately first (see 'diagnose' output) before running this."
            ),
            "case_only_count": result["case_only_count"],
        }

    if result["case_only_count"] == 0:
        return {"status": "no_data", "message": "No case-only drift found."}

    where = "WHERE status = 'missing'"
    params = []
    if root_path:
        where += " AND canonical_path LIKE ?"
        params.append(normalize_path(root_path) + "%")
    missing_rows = [dict(r) for r in conn.execute(f"SELECT * FROM files {where};", params).fetchall()]

    present_rows = conn.execute(
        "SELECT canonical_path, hash, size_bytes FROM files WHERE status='present' AND hash IS NOT NULL;"
    ).fetchall()
    present_by_key = {(normalize_path(p["canonical_path"]), p["hash"], p["size_bytes"]): p["canonical_path"]
                       for p in present_rows}

    to_delete = []
    for m in missing_rows:
        if not m["hash"]:
            continue
        key = (normalize_path(m["canonical_path"]), m["hash"], m["size_bytes"])
        match = present_by_key.get(key)
        if match and match != m["canonical_path"]:
            to_delete.append(m)

    if not to_delete:
        return {"status": "no_data", "message": "No case-only drift rows resolved to concrete ids."}

    if dry_run:
        return {
            "status": "dry_run_complete",
            "would_delete_count": len(to_delete),
            "examples": [r["canonical_path"] for r in to_delete[:10]],
        }

    try:
        preview = journal.preview_operation(
            conn, action_type="case_drift_cleanup", tier=3,
            target_path=root_path or "(all)",
            planned_changes={"stale_rows_to_remove": len(to_delete)},
        )
        op_id = journal.begin_transaction(conn, preview, previous_state={"deleted_rows": to_delete})
    except journal.ExecutionDisabled as e:
        return {"status": "blocked_by_kill_switch", "reason": str(e)}

    ids = [r["id"] for r in to_delete]
    CHUNK = 500
    for i in range(0, len(ids), CHUNK):
        chunk = ids[i:i + CHUNK]
        conn.execute(f"DELETE FROM files WHERE id IN ({','.join('?' * len(chunk))});", chunk)
        if verbose and (i // CHUNK) % 10 == 0:
            print(f"  ...cleaned {min(i + CHUNK, len(ids))}/{len(ids)}")

    journal.complete_operation(conn, op_id, new_state={"deleted_count": len(to_delete)}, verified=True)
    conn.commit()

    return {"status": "complete", "deleted_count": len(to_delete), "op_id": op_id}


def undo_case_drift_cleanup(conn, op_id: int) -> dict:
    row = conn.execute("SELECT * FROM action_log WHERE id = ?;", (op_id,)).fetchone()
    if row is None:
        return {"status": "failed", "reason": "not_found"}

    def _reverse(previous_state: dict):
        for r in previous_state["deleted_rows"]:
            conn.execute(
                """INSERT INTO files (id, canonical_path, hash, size_bytes, modified_at,
                                       first_seen_at, last_seen_at, status, project_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);""",
                (r["id"], r["canonical_path"], r["hash"], r["size_bytes"], r["modified_at"],
                 r["first_seen_at"], r["last_seen_at"], r["status"], r["project_id"]),
            )
        conn.commit()

    return journal.undo_operation(conn, op_id, _reverse)
