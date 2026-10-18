"""Operation receipt summaries for Journey."""

from __future__ import annotations

import json
from typing import Any
from core.recovery_inspection import inspect_operation


def _json_summary(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {"present": False, "keys": []}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {"present": True, "keys": [], "parseable": False}
    if isinstance(value, dict):
        return {"present": True, "keys": sorted(value.keys()), "parseable": True}
    if isinstance(value, list):
        return {"present": True, "keys": [], "parseable": True, "items": len(value)}
    return {"present": True, "keys": [], "parseable": True, "type": type(value).__name__}


def list_receipts(conn, limit: int = 10) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT id, action_type, tier, target_path, previous_state, new_state,
                  status, performed_at, reversed_at
           FROM action_log
           ORDER BY id DESC
           LIMIT ?;""",
        (limit,),
    ).fetchall()
    receipts = []
    for row in rows:
        action_type = row["action_type"]
        recovery = inspect_operation(conn, row['id'])
        undo_available = recovery['state'] == 'UNDO_AVAILABLE' and not action_type.startswith('undo:')
        receipts.append(
            {
                "op_id": row["id"],
                "label": f"OP-{row['id']:06d}",
                "action_type": action_type,
                "tier": row["tier"],
                "target_path": row["target_path"],
                "status": row["status"],
                "performed_at": row["performed_at"],
                "reversed_at": row["reversed_at"],
                "before": _json_summary(row["previous_state"]),
                "after": _json_summary(row["new_state"]),
                "undo_available": undo_available,
                "undo_state": recovery['state'],
                "recovery": recovery,
                "undo_command": f".\\ark.cmd undo {row['id']}" if undo_available else None,
            }
        )
    return receipts
