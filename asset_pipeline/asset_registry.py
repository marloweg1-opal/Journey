from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any


INDEX_NAME = "asset-index.json"


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def fingerprint(operation: str, source_sha256: Any, options: dict[str, Any]) -> str:
    payload = {
        "operation": operation,
        "source_sha256": source_sha256,
        "options": options,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def load_index(pipeline_root: Path) -> dict[str, Any]:
    index_path = pipeline_root / INDEX_NAME
    if not index_path.exists():
        return {"version": 1, "entries": {}}
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "entries": {}}
    if not isinstance(data, dict):
        return {"version": 1, "entries": {}}
    data.setdefault("version", 1)
    data.setdefault("entries", {})
    if not isinstance(data["entries"], dict):
        data["entries"] = {}
    return data


def save_index(pipeline_root: Path, index: dict[str, Any]) -> Path:
    index_path = pipeline_root / INDEX_NAME
    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
    return index_path


def existing_entry(pipeline_root: Path, key: str) -> dict[str, Any] | None:
    entry = load_index(pipeline_root)["entries"].get(key)
    if not isinstance(entry, dict):
        return None
    job_dir = entry.get("job_dir")
    if job_dir and Path(job_dir).exists():
        return entry
    return None


def record_entry(
    pipeline_root: Path,
    key: str,
    *,
    operation: str,
    source_sha256: Any,
    options: dict[str, Any],
    job: str,
    job_dir: Path,
    outputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    index = load_index(pipeline_root)
    entry = {
        "fingerprint": key,
        "operation": operation,
        "source_sha256": source_sha256,
        "options": options,
        "job": job,
        "job_dir": str(job_dir),
        "outputs": outputs or {},
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    index["entries"][key] = entry
    save_index(pipeline_root, index)
    return entry
