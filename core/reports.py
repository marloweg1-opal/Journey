"""
Mini ARK report generator.

Read-only. Turns the ledger's raw rows into something a human can
actually read in one pass -- the difference between "the data exists"
and "the data is usable."
"""

import time
from pathlib import Path


def generate_scan_report(conn, root_path: str = None) -> str:
    """
    Produces a Markdown report summarizing what the ledger currently
    knows: scan history, file counts by status, and unreconciled events
    -- optionally scoped to one root path.
    """
    lines = []
    lines.append(f"# Mini ARK Scan Report")
    lines.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    if root_path:
        lines.append(f"Scope: `{root_path}`")
    lines.append("")

    path_filter = (str(root_path) + "%") if root_path else "%"

    scans = conn.execute(
        """SELECT * FROM scans WHERE root_path LIKE ?
           ORDER BY started_at DESC LIMIT 10;""",
        (path_filter,),
    ).fetchall()

    lines.append("## Recent Scans")
    if not scans:
        lines.append("_No scans recorded yet for this scope._")
    else:
        for s in scans:
            status_mark = {"complete": "✓", "interrupted": "⚠", "running": "…", "failed": "✗"}.get(s["status"], "?")
            lines.append(f"- {status_mark} `{s['root_path']}` — {s['status']} "
                         f"({s['files_scanned'] or 0} files, started {s['started_at']})")
    lines.append("")

    total = conn.execute(
        "SELECT COUNT(*) as c FROM files WHERE canonical_path LIKE ?;", (path_filter,)
    ).fetchone()["c"]
    present = conn.execute(
        "SELECT COUNT(*) as c FROM files WHERE canonical_path LIKE ? AND status='present';", (path_filter,)
    ).fetchone()["c"]
    missing = conn.execute(
        "SELECT COUNT(*) as c FROM files WHERE canonical_path LIKE ? AND status='missing';", (path_filter,)
    ).fetchone()["c"]

    lines.append("## File Inventory")
    lines.append(f"- Total known: {total}")
    lines.append(f"- Present: {present}")
    lines.append(f"- Missing (recorded but not found on last scan): {missing}")
    lines.append("")

    unreconciled = conn.execute(
        """SELECT event_type, COUNT(*) as c FROM events
           WHERE status='raw' GROUP BY event_type;"""
    ).fetchall()

    lines.append("## Unreconciled Events")
    if not unreconciled:
        lines.append("_None. Everything raw has been processed._")
    else:
        for row in unreconciled:
            lines.append(f"- {row['event_type']}: {row['c']}")
    lines.append("")

    duplicates = conn.execute(
        """SELECT hash, COUNT(*) as c, GROUP_CONCAT(canonical_path, ' | ') as paths
           FROM files WHERE canonical_path LIKE ? AND status='present'
             AND hash NOT LIKE 'UNREADABLE:%'
           GROUP BY hash HAVING c > 1
           ORDER BY c DESC LIMIT 20;""",
        (path_filter,),
    ).fetchall()

    lines.append("## Possible Duplicates (same content hash)")
    if not duplicates:
        lines.append("_None detected._")
    else:
        for row in duplicates:
            lines.append(f"- {row['c']} copies:")
            for p in row["paths"].split(" | "):
                lines.append(f"  - `{p}`")
    lines.append("")

    return "\n".join(lines)


def write_report(conn, root_path: str, output_path: str) -> str:
    report = generate_scan_report(conn, root_path)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report)
    return str(out)
