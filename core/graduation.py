"""
Mini ARK graduation criteria.

Governing principle (Amendment 1): implementation does not confer trust.
A phase being CODED is not the same as a phase being TRUSTWORTHY. Each
phase graduates only after passing its own evidence checklist.

Pattern: Capability -> Testing -> Evidence -> Graduation -> Expanded permission.
"""

from pathlib import Path


def check_phase2_scanner(conn, test_root: str) -> dict:
    """
    Phase 2 (filesystem scanner) graduation checklist. Run this against
    a real test directory before trusting the scanner as a ledger source.

    Each check is something Mini ARK can verify about ITSELF, not a
    claim taken on faith.
    """
    from scanner.scanner import scan_path
    from db.database import record_source
    import tempfile, os, time, shutil

    results = {}
    test_dir = Path(tempfile.mkdtemp(prefix="ark_graduation_"))

    try:
        # Check 1: repeated scans of unchanged content produce stable results
        (test_dir / "stable.txt").write_text("unchanged content")
        source_id = record_source(conn, kind="graduation_test", label="phase2 check")
        r1 = scan_path(conn, str(test_dir), source_id, verbose=False)
        r2 = scan_path(conn, str(test_dir), source_id, verbose=False)
        results["stable_results_on_repeat_scan"] = (r2["added"] == 0 and r2["changed"] == 0)

        # Check 2: a real change is always detected
        time.sleep(1.1)  # ensure mtime actually differs
        (test_dir / "stable.txt").write_text("changed content")
        r3 = scan_path(conn, str(test_dir), source_id, verbose=False)
        results["changes_always_detected"] = (r3["changed"] == 1)

        # Check 3: unchanged files aren't falsely reported as changed
        r4 = scan_path(conn, str(test_dir), source_id, verbose=False)
        results["no_false_positives"] = (r4["changed"] == 0)

        # Check 4: inaccessible paths fail safely (no crash)
        try:
            r5 = scan_path(conn, "/definitely/does/not/exist", source_id, verbose=False)
            results["inaccessible_paths_fail_safely"] = (r5.get("status") == "failed")
        except Exception:
            results["inaccessible_paths_fail_safely"] = False

        # Check 5: no files are modified by scanning (read-only guarantee)
        content_before = (test_dir / "stable.txt").read_text()
        scan_path(conn, str(test_dir), source_id, verbose=False)
        content_after = (test_dir / "stable.txt").read_text()
        results["scan_is_read_only"] = (content_before == content_after)

        # Check 6: deletions are flagged missing, never silently dropped
        os.remove(test_dir / "stable.txt")
        r6 = scan_path(conn, str(test_dir), source_id, verbose=False)
        results["deletions_flagged_not_dropped"] = (r6["missing"] == 1)

        # Check 7: interruption checkpoints progress and resume produces
        # correct totals with no duplicate rows -- the standing 5-minute/
        # resumability rule.
        interrupt_dir = Path(tempfile.mkdtemp(prefix="ark_graduation_resume_"))
        for i in range(10):
            (interrupt_dir / f"f{i}.txt").write_text(f"content {i}")

        real_hash = __import__("scanner.scanner", fromlist=["hash_file"]).hash_file
        import scanner.scanner as scanner_mod
        call_count = {"n": 0}

        def flaky_hash(path):
            call_count["n"] += 1
            if call_count["n"] == 4:
                raise OSError("simulated interruption")
            return real_hash(path)

        scanner_mod.hash_file = flaky_hash
        source_id2 = record_source(conn, kind="graduation_test", label="resume check")
        r7a = scan_path(conn, str(interrupt_dir), source_id2, verbose=False)
        interrupted_correctly = (r7a["status"] == "interrupted")

        scanner_mod.hash_file = real_hash
        r7b = scan_path(conn, str(interrupt_dir), source_id2, verbose=False, resume=True)
        resume_completed = (r7b["status"] == "complete" and r7b["files_scanned"] == 10)

        row_count = conn.execute(
            "SELECT COUNT(*) as c FROM files WHERE canonical_path LIKE ?;",
            (str(interrupt_dir) + "%",),
        ).fetchone()["c"]
        no_duplicate_rows = (row_count == 10)

        shutil.rmtree(interrupt_dir, ignore_errors=True)
        results["interruption_checkpoints_and_resumes_correctly"] = (
            interrupted_correctly and resume_completed and no_duplicate_rows
        )

    finally:
        shutil.rmtree(test_dir, ignore_errors=True)

    all_passed = all(results.values())
    return {"phase": 2, "component": "filesystem_scanner", "checks": results, "graduated": all_passed}


def print_graduation_report(report: dict):
    print(f"GRADUATION CHECK: Phase {report['phase']} — {report['component']}\n")
    for check, passed in report["checks"].items():
        mark = "✓" if passed else "✗"
        print(f"  {mark} {check.replace('_', ' ')}")
    print()
    if report["graduated"]:
        print(f"[SUCCESS] Phase {report['phase']} graduates. Trustworthy enough to")
        print(f"          become a source for the ledger / expand permission.")
    else:
        print(f"[WARNING] Phase {report['phase']} does NOT graduate yet.")
        print(f"          Implementation exists; trust has not been earned.")
