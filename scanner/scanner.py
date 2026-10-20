"""
Mini ARK filesystem scanner.

Constitutional constraint (Section 18): this module performs NO
destructive or reorganizing operations. It reads, hashes, compares
against the ledger, and reports. That is all.

Standing rule: any operation that could run past ~5 minutes gets a
visible progress counter AND periodic commits, so a disconnection or
interruption never loses more than a few seconds of work. Resume picks
up from the last durably-committed point rather than starting over.
"""

import hashlib
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from db.database import get_connection, initialize_schema

FULL_HASH_LIMIT_BYTES = 50 * 1024 * 1024  # 50MB
PARTIAL_CHUNK = 1024 * 1024  # 1MB

COMMIT_INTERVAL_SECONDS = 20    # durable checkpoint at least this often
PROGRESS_INTERVAL_SECONDS = 15  # visible progress line at least this often


def normalize_path(path) -> str:
    """
    Windows' filesystem is case-insensitive: 'R:\\RuneScript' and
    'R:\\Runescript' are the SAME file, regardless of what casing you
    typed. os.path.normcase() matches that reality (lowercases on
    Windows, no-op on Linux/Mac). Every place canonical_path is
    written or compared MUST go through this, or a scan run with
    different casing than a prior run will wrongly see every file as
    both newly-added and simultaneously missing.
    """
    return os.path.normcase(str(path))


def hash_file(path: Path) -> str:
    """Return a sha256 hash. Full hash for small files, partial for large ones."""
    h = hashlib.sha256()
    size = path.stat().st_size
    try:
        with open(path, "rb") as f:
            if size <= FULL_HASH_LIMIT_BYTES:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            else:
                h.update(f.read(PARTIAL_CHUNK))
                f.seek(-PARTIAL_CHUNK, os.SEEK_END)
                h.update(f.read(PARTIAL_CHUNK))
                h.update(str(size).encode())
    except (PermissionError, OSError) as e:
        return f"UNREADABLE:{e}"
    return h.hexdigest()


def _find_resumable_scan(conn, root_path: str):
    """An interrupted scan of this exact root, most recent first."""
    return conn.execute(
        """SELECT * FROM scans WHERE root_path = ? AND status = 'interrupted'
           ORDER BY started_at DESC LIMIT 1;""",
        (str(root_path),),
    ).fetchone()


def scan_path(conn, root_path: str, source_id: int, verbose: bool = True,
              resume: bool = False) -> dict:
    """
    Read-only scan with checkpointed commits and interruption handling.

    If resume=True and a prior interrupted scan of this exact root exists,
    continues that scan's row (cumulative counts) instead of starting a
    fresh one. Already-recorded unchanged files are skip-hashed, so
    re-walking from the top after a resume is cheap -- the expensive
    part (hashing) only repeats for files not yet durably committed.
    """
    root = Path(root_path)
    if not root.exists():
        print(f"[FAILED] Path does not exist: {root_path}")
        return {"status": "failed", "reason": "path_not_found"}

    prior = _find_resumable_scan(conn, str(root)) if resume else None

    if prior:
        scan_id = prior["id"]
        added = prior["files_added"] or 0
        changed = prior["files_changed"] or 0
        missing = prior["files_missing"] or 0
        prior_file_count = prior["files_scanned"] or 0
        conn.execute("UPDATE scans SET status='running', interrupted_at=NULL WHERE id=?;", (scan_id,))
        conn.commit()
        print(f"[STARTING] Resuming scan: {root_path} (scan #{scan_id}, "
              f"{prior_file_count} files already processed before interruption)")
    else:
        cur = conn.execute(
            "INSERT INTO scans (root_path, status) VALUES (?, 'running');",
            (str(root),),
        )
        scan_id = cur.lastrowid
        conn.commit()
        added = changed = missing = 0
        print(f"[STARTING] Scan: {root_path}")

    # file_count always starts fresh for THIS pass, whether resuming or
    # not. A completing pass necessarily re-touches every file that
    # currently exists, so its own count is the true total -- carrying
    # a prior partial count forward as an offset would double-count
    # files seen in both the interrupted pass and this one.
    file_count = 0

    start = time.time()
    last_commit_time = start
    last_progress_time = start
    unchanged = errors = 0
    seen_paths = set()
    current_fpath = None

    def checkpoint(last_path):
        """Durable commit + scan-row update. Anything committed here
        survives a crash immediately after."""
        conn.execute(
            """UPDATE scans SET files_scanned=?, files_added=?, files_changed=?,
               files_missing=?, last_committed_path=? WHERE id=?;""",
            (file_count, added, changed, missing, str(last_path) if last_path else None, scan_id),
        )
        conn.commit()

    try:
        for dirpath, dirnames, filenames in os.walk(root):
            for fname in filenames:
                fpath = Path(dirpath) / fname
                current_fpath = fpath
                file_count += 1
                norm_path = normalize_path(fpath)
                seen_paths.add(norm_path)

                now = time.time()
                if verbose and (now - last_progress_time) >= PROGRESS_INTERVAL_SECONDS:
                    elapsed = round(now - start, 0)
                    print(f"[WORKING] {file_count} files scanned so far "
                          f"({int(elapsed)}s elapsed, currently in {dirpath})")
                    last_progress_time = now

                try:
                    stat = fpath.stat()
                except (PermissionError, OSError):
                    errors += 1
                    continue

                existing = conn.execute(
                    "SELECT id, hash, size_bytes, modified_at FROM files WHERE canonical_path = ?;",
                    (norm_path,),
                ).fetchone()

                mtime_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(stat.st_mtime))

                if existing:
                    if existing["size_bytes"] == stat.st_size and existing["modified_at"] == mtime_iso:
                        conn.execute(
                            "UPDATE files SET last_seen_at = datetime('now'), status='present' WHERE id = ?;",
                            (existing["id"],),
                        )
                        unchanged += 1
                    else:
                        new_hash = hash_file(fpath)
                        conn.execute(
                            """UPDATE files SET hash=?, size_bytes=?, modified_at=?,
                               last_seen_at=datetime('now'), status='present' WHERE id=?;""",
                            (new_hash, stat.st_size, mtime_iso, existing["id"]),
                        )
                        conn.execute(
                            """INSERT INTO events (event_type, description, source_id, status)
                               VALUES ('file_changed', ?, ?, 'raw');""",
                            (f"{fpath} changed (hash/size/mtime delta detected)", source_id),
                        )
                        changed += 1
                else:
                    new_hash = hash_file(fpath)
                    conn.execute(
                        """INSERT INTO files (canonical_path, hash, size_bytes, modified_at)
                           VALUES (?, ?, ?, ?);""",
                        (norm_path, new_hash, stat.st_size, mtime_iso),
                    )
                    conn.execute(
                        """INSERT INTO events (event_type, description, source_id, status)
                           VALUES ('file_added', ?, ?, 'raw');""",
                        (f"{fpath} newly seen", source_id),
                    )
                    added += 1

                now = time.time()
                if (now - last_commit_time) >= COMMIT_INTERVAL_SECONDS:
                    checkpoint(fpath)
                    last_commit_time = now

    except (KeyboardInterrupt, Exception) as e:
        checkpoint(current_fpath)
        conn.execute(
            "UPDATE scans SET status='interrupted', interrupted_at=datetime('now') WHERE id=?;",
            (scan_id,),
        )
        conn.commit()
        print(f"\n[WARNING] Scan interrupted: {type(e).__name__}: {e}")
        print(f"  Progress saved through {file_count} files.")
        print(f"  To resume: ark scan \"{root_path}\" --resume")
        if isinstance(e, KeyboardInterrupt):
            sys.exit(130)
        return {"status": "interrupted", "scan_id": scan_id, "files_scanned": file_count}

    # Full walk completed without exception -- safe to conclude anything
    # previously recorded but not seen this pass is actually missing.
    # canonical_path is stored normalized (see normalize_path), so the
    # prefix filter must be normalized too, and GLOB (case-sensitive)
    # is used instead of LIKE (case-insensitive by default) since both
    # sides are already guaranteed to be in the same normalized case --
    # no need to rely on LIKE's quirky default behavior at all.
    norm_root_prefix = normalize_path(root) + "*"
    prior_files = conn.execute(
        "SELECT id, canonical_path FROM files WHERE canonical_path GLOB ? AND status = 'present';",
        (norm_root_prefix,),
    ).fetchall()
    for row in prior_files:
        if row["canonical_path"] not in seen_paths:
            conn.execute("UPDATE files SET status='missing' WHERE id=?;", (row["id"],))
            conn.execute(
                """INSERT INTO events (event_type, description, source_id, status)
                   VALUES ('file_missing', ?, ?, 'raw');""",
                (f"{row['canonical_path']} no longer found under scanned root", source_id),
            )
            missing += 1

    conn.execute(
        """UPDATE scans SET completed_at=datetime('now'), files_scanned=?,
           files_added=?, files_changed=?, files_missing=?, status='complete' WHERE id=?;""",
        (file_count, added, changed, missing, scan_id),
    )
    conn.commit()

    elapsed = round(time.time() - start, 1)
    result = {
        "status": "complete",
        "scan_id": scan_id,
        "files_scanned": file_count,
        "added": added,
        "changed": changed,
        "unchanged": unchanged,
        "missing": missing,
        "errors": errors,
        "elapsed_seconds": elapsed,
    }

    print(f"[SUCCESS] Scan complete: {root_path}")
    print(f"  Files scanned:  {file_count}")
    print(f"  Added:          {added}")
    print(f"  Changed:        {changed}")
    print(f"  Unchanged:      {unchanged}")
    print(f"  Missing:        {missing}")
    if errors:
        print(f"[WARNING] Unreadable/permission errors: {errors}")
    print(f"  Elapsed:        {elapsed}s")

    return result
