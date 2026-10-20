"""
Mini ARK reconcile -- diagnostic half.

analyze_symmetry() answers a specific question raised during a real R:
review: when a batch of 'added' and 'missing' events land in equal
numbers, is that a genuine mass move/rename, or a path-casing
artifact from normalize_path() not having been applied consistently
across two scans run under different code versions?

Entirely read-only. Writes nothing, proposes nothing, changes no
row's status. It exists to produce an honest, evidence-based answer
before 'reconcile' (which will eventually act on this) gets built,
rather than guessing at what the symmetry means.
"""

import time
from scanner.scanner import normalize_path


def check_canonical_path_unique(conn) -> bool:
    """
    Whether 'files' actually has a UNIQUE constraint enforced on disk --
    NOT whether schema.sql currently says it should. A constraint added
    to schema.sql after a table already exists never retroactively
    applies; SQLite can't ALTER a constraint onto an existing table,
    only rebuild it. This checks the real, current state of the table
    via its actual index list, not the schema file's intent.
    """
    indexes = conn.execute("PRAGMA index_list(files);").fetchall()
    for idx in indexes:
        if idx["unique"]:
            cols = conn.execute(f"PRAGMA index_info({idx['name']});").fetchall()
            if len(cols) == 1 and cols[0]["name"] == "canonical_path":
                return True
    return False


def _query_duplicate_groups(conn, root_path: str = None) -> list:
    """Internal: full (uncapped) duplicate-group query, shared by the
    CLI-facing find_duplicate_canonical_paths (which caps for display)
    and resolve_duplicate_rows (which needs every row to act on)."""
    where = ""
    params = []
    if root_path:
        where = "WHERE canonical_path LIKE ?"
        params.append(normalize_path(root_path) + "%")

    rows = conn.execute(
        f"""SELECT canonical_path, COUNT(*) as dupe_count,
                   GROUP_CONCAT(status) as statuses,
                   GROUP_CONCAT(id) as row_ids
            FROM files {where}
            GROUP BY canonical_path
            HAVING COUNT(*) > 1;""",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def find_duplicate_canonical_paths(conn, root_path: str = None) -> dict:
    """
    Fast (single indexed GROUP BY, not a query per row): finds every
    canonical_path with more than one row in 'files'. If
    check_canonical_path_unique() is False, this is very likely
    non-empty -- nothing has ever prevented it.
    """
    all_groups = _query_duplicate_groups(conn, root_path)
    return {
        "status": "checked",
        "unique_constraint_enforced": check_canonical_path_unique(conn),
        "duplicate_path_count": len(all_groups),
        "examples": [
            {"path": r["canonical_path"], "row_count": r["dupe_count"],
             "statuses": r["statuses"], "row_ids": r["row_ids"]}
            for r in all_groups[:15]
        ],
    }


def analyze_symmetry(conn, root_path: str = None, verbose: bool = True) -> dict:
    """
    Cross-references every 'missing' file against every 'present' file
    sharing its hash+size, to distinguish three cases:

      - case_only: same hash, and the two paths are IDENTICAL once
        both are run through normalize_path(). This is not a move --
        it's the same file, previously recorded under a path with
        different casing (almost always because it was written by an
        older scan that predates consistent normalize_path() use).
        The 'missing' status here is simply wrong.

      - real_move: same hash, genuinely different path even after
        normalization. This is an actual relocation.

      - unmatched: a 'missing' file with no hash+size match anywhere
        in the current 'present' set. Genuinely gone, or unrehashed --
        no pairing possible from this data alone.

    Performance note: this loads every 'present' row's (hash, size) ->
    path index into memory ONCE up front, rather than querying per
    missing row -- a prior version did one query per missing file,
    which took over 2 hours against a 300MB ledger with 60k+ missing
    rows. This version is a single bulk load plus in-memory lookups.
    """
    where_clause = "WHERE status = 'missing'"
    params = []
    if root_path:
        where_clause += " AND canonical_path LIKE ?"
        params.append(normalize_path(root_path) + "%")

    missing_rows = conn.execute(
        f"SELECT id, canonical_path, hash, size_bytes FROM files {where_clause};",
        params,
    ).fetchall()

    if verbose:
        print(f"  Loaded {len(missing_rows)} missing file(s). Building present-file index...")

    present_rows = conn.execute(
        "SELECT canonical_path, hash, size_bytes FROM files WHERE status = 'present' AND hash IS NOT NULL;"
    ).fetchall()

    present_index = {}
    for p in present_rows:
        present_index.setdefault((p["hash"], p["size_bytes"]), []).append(p["canonical_path"])

    if verbose:
        print(f"  Present-file index built ({len(present_rows)} rows). Matching...")

    case_only, real_moves, unmatched = [], [], []
    last_report = time.time()

    for i, m in enumerate(missing_rows):
        if verbose and (time.time() - last_report) >= 15:
            print(f"  ...matched {i}/{len(missing_rows)}")
            last_report = time.time()

        if not m["hash"]:
            unmatched.append({"path": m["canonical_path"], "reason": "no hash recorded"})
            continue

        candidates = present_index.get((m["hash"], m["size_bytes"]))
        if not candidates:
            unmatched.append({"path": m["canonical_path"], "reason": "no matching hash+size among present files"})
            continue

        matched_case_only = False
        for c in candidates:
            if c == m["canonical_path"]:
                continue  # a literal duplicate row -- handled by find_duplicate_canonical_paths, not here
            if normalize_path(c) == normalize_path(m["canonical_path"]):
                case_only.append({"missing_as_recorded": m["canonical_path"], "present_as_recorded": c})
                matched_case_only = True
                break
        if not matched_case_only:
            other = next((c for c in candidates if c != m["canonical_path"]), None)
            if other:
                real_moves.append({"old_path": m["canonical_path"], "new_path": other})
            else:
                unmatched.append({"path": m["canonical_path"],
                                   "reason": "only match is itself -- literal duplicate row, see find_duplicate_canonical_paths"})

    total = len(missing_rows)
    if total == 0:
        verdict = "NOTHING MISSING -- clean"
    elif len(case_only) > total * 0.5:
        verdict = "MOSTLY CASE-DRIFT"
    elif len(real_moves) > total * 0.5:
        verdict = "MOSTLY REAL MOVES"
    elif len(unmatched) > total * 0.5:
        verdict = "MOSTLY UNMATCHED (genuinely gone or unrehashed)"
    else:
        verdict = "MIXED -- no single explanation dominates"

    return {
        "status": "analyzed",
        "total_missing": total,
        "case_only_count": len(case_only),
        "case_only_examples": case_only[:10],
        "real_move_count": len(real_moves),
        "real_move_examples": real_moves[:10],
        "unmatched_count": len(unmatched),
        "unmatched_examples": unmatched[:10],
        "verdict": verdict,
    }
