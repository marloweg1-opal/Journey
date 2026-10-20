"""Project-neutral date index.

Records relevant date data for files without rewriting the files.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from core.naming import extract_date_token


def _iso_from_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value).replace(microsecond=0).isoformat()


def file_date_record(path: Path) -> dict[str, Any]:
    _, filename_date = extract_date_token(path.stem)
    stat = path.stat()
    chosen_source = "filename" if filename_date else "modified_time"
    chosen_date = filename_date or datetime.fromtimestamp(stat.st_mtime).strftime("%Y%m%d")
    return {
        "path": str(path),
        "name": path.name,
        "extension": path.suffix.lower(),
        "filename_date": filename_date,
        "created_time": _iso_from_timestamp(stat.st_ctime),
        "modified_time": _iso_from_timestamp(stat.st_mtime),
        "chosen_date": chosen_date,
        "chosen_source": chosen_source,
        "status": "indexed",
    }


def iter_files(root: Path, recursive: bool = False, limit: int = 200):
    if root.is_file():
        yield root
        return
    iterator = root.rglob("*") if recursive else root.glob("*")
    count = 0
    for path in iterator:
        if not path.is_file():
            continue
        yield path
        count += 1
        if count >= limit:
            break


def build_date_index(root_value: str, docs_root: str, recursive: bool = False, limit: int = 200) -> dict[str, Any]:
    root = Path(root_value)
    if not root.exists():
        raise FileNotFoundError(f"Path does not exist: {root}")
    records = [file_date_record(path) for path in iter_files(root, recursive=recursive, limit=limit)]
    docs = Path(docs_root)
    docs.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = docs / f"DATE_INDEX_{stamp}.json"
    payload = {
        "status": "indexed",
        "root": str(root),
        "recursive": recursive,
        "limit": limit,
        "record_count": len(records),
        "output_path": str(output_path),
        "records": records,
        "mutation": "none",
        "policy": "Date data is saved as an index first; embedded metadata writes require a separate approved mutation.",
    }
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    return payload
