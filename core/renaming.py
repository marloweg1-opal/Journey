"""
Mini ARK renaming -- batch rename via an explicit template + ordered
file list. A rename is just a move to a new filename (same or
different directory), so this reuses apply.py's execution path
entirely rather than inventing new mutation logic -- propose here,
approve/apply/undo exactly as any other proposal.

Per HEXSEED doctrine Sec. 7: naming conventions must be explicit and
approved, never invented per-file. This tool only ever applies
EXACTLY the template given -- it does not guess a scheme.
"""

from pathlib import Path
from core.apply import add_proposal_item


def build_rename_plan(file_paths: list, template: str, start_index: int = 1,
                       pad_width: int = 2, dest_dir: str = None) -> list:
    """
    template uses {n} for the auto-incrementing index, e.g.
    'heartstone_care_rail_v{n}' -> heartstone_care_rail_v01, v02, ...
    Original extension is preserved automatically. If dest_dir is
    None, each file is renamed in place (same directory it's already in).
    """
    plan = []
    for i, src in enumerate(file_paths):
        src_path = Path(src)
        index = start_index + i
        n_str = str(index).zfill(pad_width)
        new_stem = template.format(n=n_str) if "{n}" in template else f"{template}{n_str}"
        new_name = new_stem + src_path.suffix
        dest_folder = Path(dest_dir) if dest_dir else src_path.parent
        dest_path = dest_folder / new_name
        plan.append({"source": str(src_path), "dest": str(dest_path)})
    return plan


def propose_rename_sequence(conn, file_paths: list, template: str, start_index: int = 1,
                             pad_width: int = 2, dest_dir: str = None,
                             project_id: int = None) -> dict:
    plan = build_rename_plan(file_paths, template, start_index, pad_width, dest_dir)

    description = (
        f"Batch rename {len(plan)} file(s) using template '{template}' "
        f"(starting at {start_index}, zero-padded to {pad_width} digit(s)). "
        f"This is a real rename (move mode) -- review each item before approving."
    )
    cur = conn.execute(
        """INSERT INTO proposals (description, project_id, severity, batch_key, status)
           VALUES (?, ?, 'decision', ?, 'pending');""",
        (description, project_id, f"rename:{template}"),
    )
    proposal_id = cur.lastrowid

    for item in plan:
        add_proposal_item(conn, proposal_id, item["source"], item["dest"], requested_mode="move")
    conn.commit()

    return {
        "status": "proposed",
        "proposal_id": proposal_id,
        "item_count": len(plan),
        "plan": plan,
    }
