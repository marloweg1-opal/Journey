"""
Profile migration and R: hierarchy planning for Mini ARK.

This module is copy-first. It maps old user-profile-shaped roots on R: into
Project ARK destinations, stages files by copying and verifying size, and
writes hierarchy recommendations. It never deletes profile roots.
"""

import csv
import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

from core.classify import classify_path


DEFAULT_PROFILE_ROOTS = [
    r"R:\Users",
    r"R:\Junior",
    r"R:\Downloads",
]

DEFAULT_TARGET_ROOT = r"R:\RuneScript\_ProfileMigration_Staging_Clean"
DEFAULT_SCAN_ROOT = r"R:\\"

SKIP_DIR_NAMES = {
    "$RECYCLE.BIN", "System Volume Information", "Windows", "Program Files",
    "Program Files (x86)", "ProgramData", "Boot", "Recovery", "OneDriveTemp",
    "__pycache__", ".git", "node_modules", ".pytest_cache", "AppData",
    "Application Data", "Local Settings", "NetHood", "PrintHood", "Recent",
    "SendTo", "Start Menu", "Templates",
}

SKIP_DIR_PREFIXES = (
    "defaultuser",
)

SKIP_USER_PROFILE_DIRS = {
    "All Users", "Default", "Default User",
}

SYSTEM_TOP_LEVEL = {
    "$RECYCLE.BIN", "System Volume Information", "Windows", "Program Files",
    "Program Files (x86)", "ProgramData", "Boot", "Recovery", "Documents and Settings",
    "hiberfil.sys", "pagefile.sys", "swapfile.sys", "DumpStack.log.tmp",
}


@dataclass
class ProfileItem:
    source_path: str
    destination_path: str
    size_bytes: int
    modified_at: str
    bucket: str
    confidence: str
    owner: str
    lifecycle_class: str
    subject_type: str
    placement: str
    profile_root: str


def _now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


def _safe_part(value: str, max_len: int = 90) -> str:
    value = value.strip().replace("\\", "_").replace("/", "_").replace(":", "")
    value = re.sub(r"[^A-Za-z0-9._ -]+", "_", value)
    value = re.sub(r"\s+", "_", value).strip("._- ")
    return (value or "unnamed")[:max_len]


def _is_relative_to(path: Path, possible_parent: Path) -> bool:
    try:
        path.resolve().relative_to(possible_parent.resolve())
        return True
    except (OSError, ValueError):
        return False


def _iter_files(root: Path, excluded_roots: list[Path] | None = None):
    if not root.exists():
        return
    excluded_roots = excluded_roots or []
    for current, dirnames, filenames in os.walk(root):
        current_path = Path(current)
        if any(_is_relative_to(current_path, excluded) for excluded in excluded_roots):
            dirnames[:] = []
            continue
        kept = []
        for name in dirnames:
            lower = name.lower()
            if name in SKIP_DIR_NAMES or name in SKIP_USER_PROFILE_DIRS:
                continue
            if any(lower.startswith(prefix) for prefix in SKIP_DIR_PREFIXES):
                continue
            if any(_is_relative_to(current_path / name, excluded) for excluded in excluded_roots):
                continue
            kept.append(name)
        dirnames[:] = kept
        for filename in filenames:
            path = current_path / filename
            try:
                if path.is_file():
                    yield path
            except OSError:
                continue


def _destination_bucket(classification: dict) -> str:
    bucket = classification["bucket"].replace("/", "\\")
    if bucket.startswith("RuneScript\\Projects\\"):
        return bucket
    if bucket.startswith("Media\\"):
        return bucket
    if bucket.startswith("Library\\"):
        return bucket
    if bucket.startswith("System_Records\\"):
        return bucket
    if bucket.startswith("Intake\\"):
        return bucket
    return "Intake\\Needs_Classification"


def _destination_for(source: Path, profile_root: Path, target_root: Path, classification: dict) -> Path:
    bucket = _destination_bucket(classification)
    root_label = _safe_part(str(profile_root), max_len=40)
    digest = hashlib.sha1(str(source).lower().encode("utf-8")).hexdigest()[:12]
    try:
        rel = source.relative_to(profile_root)
        parent_parts = [_safe_part(part, max_len=50) for part in rel.parts[:-1]]
    except ValueError:
        parent_parts = []
    safe_stem = _safe_part(source.stem, max_len=80)
    safe_name = f"{safe_stem}__{digest}{source.suffix.lower()}"
    return target_root / bucket / root_label / Path(*parent_parts) / safe_name


def build_profile_migration_map(profile_roots: list[str], target_root: str,
                                docs_root: str, limit: int | None = None) -> dict:
    target = Path(target_root)
    docs = Path(docs_root)
    docs.mkdir(parents=True, exist_ok=True)
    items: list[ProfileItem] = []
    skipped_roots = []
    seen = set()

    for root_text in profile_roots:
        root = Path(root_text)
        if not root.exists():
            skipped_roots.append({"path": root_text, "reason": "missing"})
            continue
        for path in _iter_files(root, excluded_roots=[target]):
            if limit is not None and len(items) >= limit:
                break
            key = str(path).lower()
            if key in seen:
                continue
            seen.add(key)
            try:
                stat = path.stat()
            except OSError:
                continue
            classification = classify_path(str(path))
            items.append(ProfileItem(
                source_path=str(path),
                destination_path=str(_destination_for(path, root, target, classification)),
                size_bytes=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                bucket=_destination_bucket(classification),
                confidence=classification["confidence"],
                owner=classification["owner"],
                lifecycle_class=classification["lifecycle_class"],
                subject_type=classification["subject_type"],
                placement=classification["placement"],
                profile_root=str(root),
            ))
        if limit is not None and len(items) >= limit:
            break

    stamp = _now_stamp()
    json_path = docs / f"R_PROFILE_MIGRATION_MAP_{stamp}.json"
    md_path = docs / f"R_PROFILE_MIGRATION_MAP_{stamp}.md"
    csv_path = docs / f"R_PROFILE_MIGRATION_MAP_{stamp}.csv"
    buckets = {}
    for item in items:
        buckets.setdefault(item.bucket, {"count": 0, "bytes": 0})
        buckets[item.bucket]["count"] += 1
        buckets[item.bucket]["bytes"] += item.size_bytes
    plan = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "profile_roots": profile_roots,
        "target_root": target_root,
        "item_count": len(items),
        "total_bytes": sum(item.size_bytes for item in items),
        "bucket_summary": buckets,
        "skipped_roots": skipped_roots,
        "items": [asdict(item) for item in items],
        "execution_policy": "copy_verify_no_delete_profile_migration",
    }
    json_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    _write_profile_markdown(md_path, plan)
    _write_profile_csv(csv_path, plan["items"])
    plan["json_path"] = str(json_path)
    plan["markdown_path"] = str(md_path)
    plan["csv_path"] = str(csv_path)
    return plan


def _write_profile_csv(path: Path, items: list[dict]) -> None:
    fields = [
        "bucket", "confidence", "owner", "lifecycle_class", "subject_type",
        "placement", "size_bytes", "modified_at", "profile_root",
        "source_path", "destination_path",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for item in items:
            writer.writerow(item)


def _write_profile_markdown(path: Path, plan: dict) -> None:
    lines = [
        "# R: User Profile Migration Map",
        "",
        f"- Created: {plan['created_at']}",
        f"- Target root: `{plan['target_root']}`",
        f"- Items mapped: {plan['item_count']}",
        f"- Total bytes: {plan['total_bytes']}",
        "",
        "## Safety Policy",
        "",
        "- Copy first.",
        "- Verify copied size.",
        "- Do not delete originals.",
        "- Treat user-profile roots as source containers, not final homes.",
        "- Review staged files before any profile-root cleanup.",
        "",
        "## Profile Roots",
        "",
    ]
    for root in plan["profile_roots"]:
        lines.append(f"- `{root}`")
    lines += ["", "## Destination Summary", ""]
    for bucket, summary in sorted(plan["bucket_summary"].items()):
        lines.append(f"- `{bucket}`: {summary['count']} files, {summary['bytes']} bytes")
    lines += ["", "## First Mapped Items", ""]
    for item in plan["items"][:120]:
        lines.append(f"- `{item['source_path']}`")
        lines.append(f"  - Destination: `{item['destination_path']}`")
        lines.append(f"  - Bucket: `{item['bucket']}` ({item['confidence']})")
    if len(plan["items"]) > 120:
        lines.append(f"- ... {len(plan['items']) - 120} more in JSON/CSV maps")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def execute_profile_migration_map(plan_path: str) -> dict:
    raise PermissionError(
        "STEWARDSHIP_REVIEW_REQUIRED: Legacy profile staging is held pending "
        "journaled, no-replace execution and affirmative action evidence. "
        "No plan or source was read."
    )
    plan_file = Path(plan_path)
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    target = Path(plan["target_root"])
    manifests = target / "00_MANIFESTS"
    manifests.mkdir(parents=True, exist_ok=True)

    copied = []
    failed = []
    for item in plan["items"]:
        source = Path(item["source_path"])
        dest = Path(item["destination_path"])
        try:
            if not source.exists():
                raise FileNotFoundError(str(source))
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists() and dest.stat().st_size == source.stat().st_size:
                copied.append({"source": str(source), "dest": str(dest), "already_present": True, "bucket": item["bucket"]})
                continue
            shutil.copy2(source, dest)
            if dest.stat().st_size != source.stat().st_size:
                raise RuntimeError("copy size verification failed")
            copied.append({"source": str(source), "dest": str(dest), "already_present": False, "bucket": item["bucket"]})
        except Exception as exc:
            failed.append({"source": str(source), "dest": str(dest), "bucket": item["bucket"], "reason": f"{type(exc).__name__}: {exc}"})

    stamp = _now_stamp()
    result_path = manifests / f"R_PROFILE_MIGRATION_STAGE_RESULT_{stamp}.json"
    manifest_json = manifests / Path(plan_file.name).name
    manifest_json.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    result = {
        "completed_at": datetime.now().isoformat(timespec="seconds"),
        "plan_path": str(plan_file),
        "target_root": plan["target_root"],
        "copied_count": len(copied),
        "failed_count": len(failed),
        "originals_left_in_place": True,
        "files_deleted": 0,
        "profile_roots_removed": 0,
        "copied": copied[:250],
        "failed": failed,
    }
    result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    result["result_path"] = str(result_path)
    result["manifest_json"] = str(manifest_json)
    return result


def scan_r_hierarchy(root_path: str, docs_root: str, max_depth: int = 2) -> dict:
    root = Path(root_path)
    docs = Path(docs_root)
    docs.mkdir(parents=True, exist_ok=True)
    entries = []
    if not root.exists():
        raise FileNotFoundError(root_path)

    for child in root.iterdir():
        name = child.name
        try:
            is_dir = child.is_dir()
            is_file = child.is_file()
        except OSError:
            continue
        if name in SYSTEM_TOP_LEVEL:
            recommendation = "reserve_system_managed"
            proposed_home = str(child)
            rationale = "Windows/system-managed path; keep out of ARK organization."
        elif name in {"Users", "Junior", "Downloads"}:
            recommendation = "migrate_profile_source_then_review_empty_root"
            proposed_home = DEFAULT_TARGET_ROOT
            rationale = "User-profile-shaped source container; classify contents into real destinations."
        elif name == "Projects":
            recommendation = "keep_project_source_or_merge_under_runescript_projects"
            proposed_home = r"R:\RuneScript\Projects"
            rationale = "Project-bearing root; use RuneScript project architecture as the long-term index."
        elif name == "RuneScript":
            recommendation = "keep_as_primary_project_architecture"
            proposed_home = str(child)
            rationale = "Primary ARK/RuneScript project structure."
        elif name in {"Media", "Grimoire", "Lab", "Installers", "Staging", "07_Temp"}:
            recommendation = "keep_but_normalize_subfolders"
            proposed_home = str(child)
            rationale = "Recognizable lane; scan deeper before moving anything."
        elif name.startswith("_ark"):
            recommendation = "keep_mini_ark_control_area"
            proposed_home = str(child)
            rationale = "Mini ARK-managed control/quarantine area."
        else:
            recommendation = "review_and_assign_lane"
            proposed_home = r"R:\Intake\Needs_Classification"
            rationale = "No hard system or project signal at top level."

        file_count = 1 if is_file else 0
        dir_count = 0
        total_bytes = 0
        if is_file:
            try:
                total_bytes = child.stat().st_size
            except OSError:
                total_bytes = 0
        elif is_dir and name not in SYSTEM_TOP_LEVEL:
            for current, dirnames, filenames in os.walk(child):
                depth = len(Path(current).relative_to(child).parts)
                if depth >= max_depth:
                    dirnames[:] = []
                dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES]
                dir_count += len(dirnames)
                for filename in filenames:
                    file_count += 1
                    try:
                        total_bytes += (Path(current) / filename).stat().st_size
                    except OSError:
                        pass

        entries.append({
            "path": str(child),
            "name": name,
            "kind": "directory" if is_dir else "file",
            "file_count_depth_limited": file_count,
            "dir_count_depth_limited": dir_count,
            "bytes_depth_limited": total_bytes,
            "recommendation": recommendation,
            "proposed_home": proposed_home,
            "rationale": rationale,
        })

    stamp = _now_stamp()
    json_path = docs / f"R_HIERARCHY_SCAN_{stamp}.json"
    md_path = docs / f"R_HIERARCHY_SCAN_{stamp}.md"
    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "root_path": root_path,
        "max_depth": max_depth,
        "entry_count": len(entries),
        "entries": sorted(entries, key=lambda item: item["name"].lower()),
        "suggested_hierarchy": [
            r"R:\Projects",
            r"R:\Projects\CareBloomOS",
            DEFAULT_TARGET_ROOT,
            r"R:\Media",
            r"R:\Library",
            r"R:\System_Records",
            r"R:\In_Transit",
            r"R:\In_Transit\En_Route",
            r"R:\_ark_quarantine",
        ],
    }
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    _write_hierarchy_markdown(md_path, report)
    report["json_path"] = str(json_path)
    report["markdown_path"] = str(md_path)
    return report


def _write_hierarchy_markdown(path: Path, report: dict) -> None:
    lines = [
        "# R: Folder Organization Scan",
        "",
        f"- Created: {report['created_at']}",
        f"- Root: `{report['root_path']}`",
        f"- Depth limit for counts: {report['max_depth']}",
        f"- Top-level entries: {report['entry_count']}",
        "",
        "## Suggested Long-Term Hierarchy",
        "",
    ]
    for item in report["suggested_hierarchy"]:
        lines.append(f"- `{item}`")
    lines += ["", "## Top-Level Recommendations", ""]
    for entry in report["entries"]:
        lines.append(f"- `{entry['path']}`")
        lines.append(f"  - Recommendation: {entry['recommendation']}")
        lines.append(f"  - Proposed home: `{entry['proposed_home']}`")
        lines.append(f"  - Files counted: {entry['file_count_depth_limited']}; folders counted: {entry['dir_count_depth_limited']}")
        lines.append(f"  - Why: {entry['rationale']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
