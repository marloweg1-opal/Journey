"""
Mini ARK organization proposer.

Constitutional constraint: this module NEVER creates, moves, renames,
or deletes a real file or folder. It only writes rows into the
`proposals` table describing what it THINKS should happen. Executing
a proposal is a separate, later, explicitly-approved action (Tier 3+)
that does not exist in this build yet.

This is Tier 2 ("Propose") made concrete: Mini ARK may suggest actions
without performing them.
"""

import fnmatch
import json
import subprocess
from collections import defaultdict
from pathlib import Path


# Simple extension -> category map. Deliberately conservative and
# editable -- this is a starting proposal, not a taxonomy decree.
_CATEGORY_MAP = {
    ".mp4": "Video", ".mov": "Video", ".mkv": "Video", ".avi": "Video",
    ".png": "Images", ".jpg": "Images", ".jpeg": "Images", ".gif": "Images", ".webp": "Images",
    ".psd": "Design", ".ai": "Design", ".fig": "Design",
    ".py": "Code", ".ps1": "Code", ".js": "Code", ".ts": "Code", ".sh": "Code",
    ".md": "Documents", ".txt": "Documents", ".pdf": "Documents", ".docx": "Documents",
    ".csv": "Data", ".json": "Data", ".sqlite": "Data", ".xlsx": "Data",
    ".zip": "Archives", ".rar": "Archives", ".7z": "Archives",
}

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic"}
_VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".wmv", ".mts", ".m2ts"}

# Duration buckets in seconds. Editable -- these are a starting point,
# not a taxonomy decree, same spirit as the extension map above.
_DURATION_BUCKETS = [
    (60,    "Under_1min"),
    (300,   "1_to_5min"),
    (1200,  "5_to_20min"),
    (3600,  "20_to_60min"),
    (float("inf"), "Over_1hr"),
]


def _bucket_for_duration(seconds: float) -> str:
    for threshold, label in _DURATION_BUCKETS:
        if seconds < threshold:
            return label
    return _DURATION_BUCKETS[-1][1]


def get_video_duration(path: str, ffprobe_path: str = "ffprobe") -> float:
    """
    Real duration via ffprobe, not a filename/size guess. Returns None
    if ffprobe isn't available or the file can't be probed (corrupt,
    unsupported, etc.) -- caller decides what to do with unprobeable
    files rather than this function silently pretending a duration.
    """
    try:
        result = subprocess.run(
            [ffprobe_path, "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        return float(data["format"]["duration"])
    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError,
            ValueError, FileNotFoundError):
        return None


def _is_excluded(path: str, exclude_folders: list) -> bool:
    """
    Case-insensitive match against any path component (folder name).
    Supports wildcards via fnmatch: "All Stars*" matches "All Stars",
    "All Stars 2024", "All Stars Reel", etc. A pattern with no wildcard
    characters still matches as an exact folder name, same as before.
    """
    if not exclude_folders:
        return False
    parts_lower = [p.lower() for p in Path(path).parts]
    for pattern in exclude_folders:
        pattern_lower = pattern.lower()
        for part in parts_lower:
            if fnmatch.fnmatch(part, pattern_lower):
                return True
    return False


def analyze_and_propose(conn, root_path: str, project_id: int = None,
                          batch_key: str = None) -> dict:
    """
    Generic extension-based categorization (Video/Images/Design/Code/
    Documents/Data/Archives). Read-only analysis of already-scanned
    files. Writes PROPOSAL rows only.
    """
    path_filter = str(root_path) + "%"
    files = conn.execute(
        "SELECT canonical_path, size_bytes FROM files WHERE canonical_path LIKE ? AND status='present';",
        (path_filter,),
    ).fetchall()

    if not files:
        return {"status": "no_data", "message": "No scanned files found under this root. Run 'ark scan' first."}

    by_category = defaultdict(list)
    uncategorized = []
    for row in files:
        ext = Path(row["canonical_path"]).suffix.lower()
        category = _CATEGORY_MAP.get(ext)
        if category:
            by_category[category].append(row["canonical_path"])
        else:
            uncategorized.append(row["canonical_path"])

    proposals_written = 0
    for category, paths in by_category.items():
        description = (
            f"Placement resolution family: {len(paths)} {category} file(s). "
            f"Do not default this to project-portal shortcuts. Decide whether "
            f"the family should LEAVE, REFERENCE, MIGRATE, CANONICALIZE, "
            f"DEPLOY, QUARANTINE, or REVIEW after checking canonical home and "
            f"dependencies."
        )
        cur = conn.execute(
            """INSERT INTO proposals (description, project_id, severity, batch_key, status)
               VALUES (?, ?, 'notice', ?, 'pending');""",
            (description, project_id, batch_key or f"organize:{root_path}"),
        )
        proposal_id = cur.lastrowid

        # Broad extension groups are now family-level findings only. They do
        # not create shortcut apply-items; concrete move/reference/quarantine
        # rows should come from placement resolution after dependency checks.
        proposals_written += 1

    conn.commit()

    return {
        "status": "proposed",
        "total_files_analyzed": len(files),
        "categories_found": {k: len(v) for k, v in by_category.items()},
        "uncategorized_count": len(uncategorized),
        "proposals_written": proposals_written,
        "note": "NOTHING was moved, created, or deleted. These are proposals "
                "awaiting review -- see 'ark brief' or query the proposals table.",
    }


def analyze_media_and_propose(conn, root_path: str, exclude_folders: list = None,
                                ffprobe_path: str = "ffprobe",
                                project_id: int = None, verbose: bool = True) -> dict:
    """
    Media-specific proposal mode:
      1. Top-level split: Images vs Videos
      2. Videos further bucketed by real duration (via ffprobe), with
         results cached so re-runs and resumes never re-probe a file
         whose duration is already known.
      3. Any path containing a folder name matching an exclude pattern
         (wildcards supported) is skipped entirely.

    Read-only against the real filesystem. Writes to video_duration_cache
    (an internal cache, not a user-facing claim) and PROPOSAL rows only.
    Probing is checkpointed and resumable, per the standing 5-minute rule --
    an interruption loses at most a few seconds of probing, and simply
    re-running this function picks up where it left off automatically.
    """
    import time as _time

    exclude_folders = exclude_folders or []
    path_filter = str(root_path) + "%"

    files = conn.execute(
        "SELECT canonical_path FROM files WHERE canonical_path LIKE ? AND status='present';",
        (path_filter,),
    ).fetchall()

    if not files:
        return {"status": "no_data", "message": "No scanned files found under this root. Run 'ark scan' first."}

    images = []
    videos = []
    excluded_count = 0
    other_count = 0

    for row in files:
        p = row["canonical_path"]
        if _is_excluded(p, exclude_folders):
            excluded_count += 1
            continue
        ext = Path(p).suffix.lower()
        if ext in _IMAGE_EXTS:
            images.append(p)
        elif ext in _VIDEO_EXTS:
            videos.append(p)
        else:
            other_count += 1

    video_buckets = defaultdict(list)
    unprobeable = []

    already_cached = 0
    newly_probed = 0
    start = _time.time()
    last_commit_time = start
    last_progress_time = start
    COMMIT_INTERVAL = 20
    PROGRESS_INTERVAL = 15

    try:
        for i, path in enumerate(videos):
            now = _time.time()
            if verbose and (now - last_progress_time) >= PROGRESS_INTERVAL:
                elapsed = int(now - start)
                print(f"[WORKING] Probing videos: {i}/{len(videos)} "
                      f"({already_cached} cached, {newly_probed} newly probed, {elapsed}s elapsed)")
                last_progress_time = now

            cached = conn.execute(
                "SELECT duration_seconds, bucket FROM video_duration_cache WHERE canonical_path = ?;",
                (path,),
            ).fetchone()

            if cached and cached["duration_seconds"] is not None:
                video_buckets[cached["bucket"]].append(path)
                already_cached += 1
                continue
            elif cached:
                # previously probed and found unprobeable -- don't retry every run
                unprobeable.append(path)
                already_cached += 1
                continue

            duration = get_video_duration(path, ffprobe_path)
            if duration is None:
                unprobeable.append(path)
                conn.execute(
                    """INSERT OR REPLACE INTO video_duration_cache
                       (canonical_path, duration_seconds, bucket) VALUES (?, NULL, NULL);""",
                    (path,),
                )
            else:
                bucket = _bucket_for_duration(duration)
                video_buckets[bucket].append(path)
                conn.execute(
                    """INSERT OR REPLACE INTO video_duration_cache
                       (canonical_path, duration_seconds, bucket) VALUES (?, ?, ?);""",
                    (path, duration, bucket),
                )
            newly_probed += 1

            now = _time.time()
            if (now - last_commit_time) >= COMMIT_INTERVAL:
                conn.commit()
                last_commit_time = now

    except (KeyboardInterrupt, Exception) as e:
        conn.commit()  # save whatever was probed before the interruption
        print(f"\n[WARNING] Media analysis interrupted: {type(e).__name__}: {e}")
        print(f"  {newly_probed} video(s) probed and cached this run "
              f"({already_cached} were already cached from before).")
        print(f"  Nothing lost -- re-run the same command to resume; "
              f"already-probed videos will not be re-probed.")
        return {
            "status": "interrupted",
            "videos_probed_this_run": newly_probed,
            "videos_already_cached": already_cached,
            "videos_remaining": len(videos) - already_cached - newly_probed,
        }

    conn.commit()

    proposals_written = 0
    batch_key = f"media_organize:{root_path}"

    if images:
        cur = conn.execute(
            """INSERT INTO proposals (description, project_id, severity, batch_key, status)
               VALUES (?, ?, 'notice', ?, 'pending');""",
            (f"Placement resolution family: {len(images)} image file(s) under "
             f"'Images/'. Do not default this to shortcuts; choose LEAVE, "
             f"REFERENCE, MIGRATE, CANONICALIZE, DEPLOY, QUARANTINE, or REVIEW "
             f"after canonical-home and dependency checks.",
             project_id, batch_key),
        )
        proposals_written += 1

    for bucket_label, paths in video_buckets.items():
        cur = conn.execute(
            """INSERT INTO proposals (description, project_id, severity, batch_key, status)
               VALUES (?, ?, 'notice', ?, 'pending');""",
            (f"Placement resolution family: {len(paths)} video file(s) under "
             f"'Videos/{bucket_label}/' by real duration via ffprobe. Do not "
             f"default this to shortcuts; choose LEAVE, REFERENCE, MIGRATE, "
             f"CANONICALIZE, DEPLOY, QUARANTINE, or REVIEW after canonical-home "
             f"and dependency checks.",
             project_id, batch_key),
        )
        proposals_written += 1

    if unprobeable:
        conn.execute(
            """INSERT INTO proposals (description, project_id, severity, batch_key, status)
               VALUES (?, ?, 'decision', ?, 'pending');""",
            (f"{len(unprobeable)} video file(s) could not be probed for "
             f"duration (possibly corrupt or unsupported) and need a human "
             f"decision on how to file them: {'; '.join(unprobeable[:5])}"
             f"{' ...' if len(unprobeable) > 5 else ''}",
             project_id, batch_key),
        )
        proposals_written += 1

    conn.commit()

    return {
        "status": "proposed",
        "total_files_scanned": len(files),
        "excluded_by_folder_rule": excluded_count,
        "images_found": len(images),
        "videos_by_duration": {k: len(v) for k, v in video_buckets.items()},
        "unprobeable_videos": len(unprobeable),
        "videos_from_cache": already_cached,
        "videos_newly_probed": newly_probed,
        "other_files_ignored": other_count,
        "proposals_written": proposals_written,
        "note": "NOTHING was moved, created, or deleted. Review with 'ark brief'.",
    }
