"""Quarantine inspection and Gate A enforcement.

Legacy mutation helpers are held until retirement, dependency, journal and
recovery contracts can be verified. Inspection must never create directories.
"""
import json
from pathlib import Path
from core.action_evidence import quarantine_hold

QUARANTINE_ROOT_NAME = "_ark_quarantine"
DEFAULT_GRACE_PERIOD_DAYS = 14


def get_quarantine_root(anchor_path: Path) -> Path:
    drive_root = Path(anchor_path).anchor or Path(anchor_path).parts[0]
    return Path(drive_root) / QUARANTINE_ROOT_NAME


def quarantine_item(conn, source_path: str, action_log_id: int) -> dict:
    return {"status": "held", "reason": quarantine_hold(),
            "source_path": source_path, "action_log_id": action_log_id,
            "managed_mutations": 0}


def restore_from_quarantine(quarantined_path: str) -> dict:
    return {"status": "UNDO_REQUIRES_REVIEW",
            "reason": "Legacy manifest alone cannot establish current identity, authority, or safe restoration. No files changed.",
            "quarantined_path": quarantined_path, "managed_mutations": 0}


def list_quarantine(anchor_path: str) -> list:
    """Read existing records without creating a quarantine root."""
    manifest_path = get_quarantine_root(Path(anchor_path)) / "_manifest.jsonl"
    if not manifest_path.exists():
        return []
    entries = []
    with manifest_path.open(encoding="utf-8") as stream:
        for line in stream:
            entries.append(json.loads(line))
    return entries
