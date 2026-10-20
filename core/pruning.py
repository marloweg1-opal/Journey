"""
Mini ARK pruning -- observes empty branches for retirement review.

Constitutional constraint, same as organizer.py: this module NEVER
deletes or moves anything itself. It only writes proposals + per-file
findings. Emptiness alone never produces executable quarantine items.

Reserved folders (registered via apply.add_reservation) are treated
as occupied, never as candidates -- and because protection is
prefix-based, nothing above a reserved folder in the tree gets
flagged as empty either, since it isn't literally empty (it contains
the reserved scaffold).
"""

import os
from pathlib import Path

from core.apply import is_protected


def find_empty_branches(conn, root_path: str) -> list:
    """
    Live filesystem walk (read-only) finding the TOPMOST directory of
    each empty branch -- if a whole nested chain of folders is empty,
    this reports the highest one, not every folder within it.

    A directory counts as empty only if it has zero files AND every
    subdirectory beneath it is also empty (or doesn't exist). A
    reserved/protected directory is always treated as occupied, which
    correctly protects everything above it too.
    """
    root_path = str(Path(root_path))
    memo = {}  # dirpath -> bool (True = empty branch)

    for dirpath, dirnames, filenames in os.walk(root_path, topdown=False):
        if is_protected(conn, dirpath):
            memo[dirpath] = False
            continue
        if filenames:
            memo[dirpath] = False
            continue
        all_subs_empty = all(memo.get(os.path.join(dirpath, d), False) for d in dirnames) if dirnames else True
        memo[dirpath] = all_subs_empty

    candidates = []
    for dirpath, empty in memo.items():
        if not empty or dirpath == root_path:
            continue
        parent = os.path.dirname(dirpath)
        parent_already_reported = memo.get(parent, False) and parent != root_path
        if parent_already_reported:
            continue  # this dir will be covered by its (also-empty) parent instead

        subfolder_count = sum(1 for p in memo if p != dirpath and p.startswith(dirpath + os.sep))
        candidates.append({"path": dirpath, "nested_empty_subfolders": subfolder_count})

    candidates.sort(key=lambda c: c["path"])
    return candidates


def propose_prune(conn, root_path: str, project_id: int = None) -> dict:
    """
    Write a review proposal and findings, with no executable action items.
    """
    candidates = find_empty_branches(conn, root_path)

    if not candidates:
        return {"status": "no_data", "message": "No empty folder branches found under this root."}

    description = (
        f"Review {len(candidates)} apparently empty folder branches. "
        "Emptiness does not establish retirement; folders may be active scaffolding or application state. "
        "No executable quarantine items are generated. Retirement and dependency evidence are required."
    )
    cur = conn.execute(
        """INSERT INTO proposals (description, project_id, severity, batch_key, status)
           VALUES (?, ?, 'decision', ?, 'pending');""",
        (description, project_id, f"prune:{root_path}"),
    )
    proposal_id = cur.lastrowid

    import json
    for c in candidates:
        conn.execute("""INSERT INTO stewardship_findings(finding_type,path,status,reason,evidence_json,recommended_action,resolution_strategy)
                        VALUES('empty_branch',?,'open',?,?,'review_retirement','REVIEW')""",
                     (c["path"], "Observed empty; retirement is unknown", json.dumps({"observation": c,"legacy_proposal_id":proposal_id,"retirement_evidence":None})))
    conn.commit()

    return {
        "status": "proposed",
        "proposal_id": proposal_id,
        "empty_folders_found": len(candidates),
        "candidates": candidates,
        "note": "Review observations are stored in stewardship_findings. No quarantine action is authorized or executable.",
    }
