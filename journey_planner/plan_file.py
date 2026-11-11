"""Persist and export planner documents outside their observed folder."""

from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import tempfile

from core.file_paths import safe_metadata
from journey_planner.catalog import (
    DECISIONS, MAX_ENTRIES, MAX_PROJECT_BYTES, File, Plan, absolute_path,
    check_local_drive, relative_path, validate_name,
)


PLAN_SUFFIX = ".journey.json"
FORMAT = "journey-folder-plan"
SCHEMA = 2


def _unique_fields(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("The plan contains duplicate fields.")
    return result


def _read(path):
    path = absolute_path(path)
    check_local_drive(path)
    if not stat.S_ISREG(safe_metadata(path).st_mode):
        raise ValueError("Choose a regular Journey plan file.")
    with path.open("rb") as stream:
        data = stream.read(MAX_PROJECT_BYTES + 1)
    if len(data) > MAX_PROJECT_BYTES:
        raise ValueError("The plan file exceeds the 24 MiB size limit.")
    return data


def open_plan(path):
    """Open the saved snapshot without accessing its original folder."""
    data = _read(path)
    try:
        document = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_fields)
        schema = document["schema"]
        if document["format"] != FORMAT or type(schema) is not int or schema not in (1, SCHEMA):
            raise ValueError("Unsupported Journey plan format or version.")
        source = document["plan"]
        plan = Plan(str(absolute_path(source["root"])), source["scanned_at"])
        if datetime.fromisoformat(plan.scanned_at).utcoffset() is None:
            raise ValueError("Missing scan timezone.")
        directories, files, gaps = source["directories"], source["files"], source["gaps"]
        if not isinstance(directories, list) or not isinstance(files, dict) or not isinstance(gaps, dict):
            raise ValueError("Invalid folder inventory.")
        if len(directories) + len(files) > MAX_ENTRIES or len(gaps) > MAX_ENTRIES:
            raise ValueError("The saved inventory exceeds the scan limit.")
        plan.directories = [relative_path(entry) for entry in directories]
        if len(set(plan.directories)) != len(plan.directories) or set(plan.directories).intersection(files):
            raise ValueError("Duplicate folder inventory entries.")
        if schema == 1:
            if type(source["limited"]) is not bool:
                raise ValueError("Invalid scan status.")
            if source["limited"]:
                plan.scan_limit = "The scan reached its time or entry limit. The earlier plan did not record which."
        else:
            plan.scan_limit = source["scan_limit"]
            if not isinstance(plan.scan_limit, str):
                raise ValueError("Invalid scan status.")
            if source["protected_root"] != "":
                protected_root = absolute_path(source["protected_root"])
                root = Path(plan.root)
                if root == protected_root or not root.is_relative_to(protected_root):
                    raise ValueError("Invalid protected source folder.")
                plan.protected_root = str(protected_root)
        if not all(isinstance(reason, str) for reason in gaps.values()):
            raise ValueError("Invalid scan gaps.")
        plan.gaps = gaps
        if not isinstance(source["collections"], list):
            raise ValueError("Invalid collection list.")
        for label in source["collections"]:
            if not isinstance(label, str) or plan.add_collection(label) != label:
                raise ValueError("Invalid collection name.")
        for key, record in files.items():
            path = relative_path(key)
            item = File(**record)
            if type(item.size) is not int or item.size < 0 or type(item.mtime_ns) is not int:
                raise ValueError("Invalid file metadata.")
            if item.collection != "" and item.collection not in plan.collections:
                raise ValueError("File refers to an unknown collection.")
            if item.decision not in DECISIONS:
                raise ValueError("Unknown file decision.")
            validate_name(path, item.name)
            plan.files[path] = item
    except (ValueError, TypeError, KeyError, RecursionError, AttributeError) as exc:
        raise ValueError("This file is not a supported Journey folder plan.") from exc
    return plan, sha256(data).hexdigest()


def _output_path(root, output, suffix):
    path = absolute_path(output)
    if not path.name.lower().endswith(suffix):
        raise ValueError(f"Use a {suffix} filename.")
    check_local_drive(path)
    if not stat.S_ISDIR(safe_metadata(path.parent).st_mode):
        raise ValueError("Choose an existing folder for the output.")
    parent = path.parent.resolve(strict=True)
    check_local_drive(parent)
    if path.is_relative_to(root) or (parent / path.name).is_relative_to(root):
        raise ValueError("Save the plan or export in a folder outside the inspected folder.")
    return parent / path.name


@contextmanager
def _save_lock(path):
    """Serialize planner updates without creating a lock file."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        kernel.CreateMutexW.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.ReleaseMutex.argtypes = kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        identity = sha256(os.path.normcase(str(path)).encode("utf-16-le")).hexdigest()
        handle = kernel.CreateMutexW(None, False, "Local\\JourneyPlanner-" + identity)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            result = kernel.WaitForSingleObject(handle, 0)
            if result == 0x102:
                raise OSError("Another Journey window is saving this plan. Try again.")
            if result not in (0, 0x80):  # Acquired or recovered after the last writer exited.
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                yield
            finally:
                kernel.ReleaseMutex(handle)
        finally:
            kernel.CloseHandle(handle)
    else:
        import fcntl

        directory = os.open(path.parent, os.O_RDONLY)
        try:
            fcntl.flock(directory, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(directory)


def _write(root, destination, suffix, data, expected=None):
    path = _output_path(root, destination, suffix)
    with _save_lock(path):
        if expected is None and os.path.lexists(path):
            raise FileExistsError("Choose a new filename. Journey leaves existing files in place.")
        if expected is not None and sha256(_read(path)).hexdigest() != expected:
            raise ValueError("This plan changed on disk. Open it again or save a new copy.")
        before = safe_metadata(path.parent)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".journey-", delete=False) as stream:
                temp_path = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            after = safe_metadata(path.parent)
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                raise ValueError("The output folder changed. Choose it again.")
            if expected is not None:
                # Recheck after writing the temporary copy to detect external edits.
                if sha256(_read(path)).hexdigest() != expected:
                    raise ValueError("This plan changed on disk. Open it again or save a new copy.")
                os.replace(temp_path, path)
            elif os.name == "nt":
                os.rename(temp_path, path)  # Windows rename refuses existing destinations.
            else:
                os.link(temp_path, path)  # Atomic creation without overwrite on the test platform.
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
    return sha256(data).hexdigest()


def save_plan(plan, path, *, expected=None):
    data = (json.dumps({"format": FORMAT, "schema": SCHEMA, "plan": asdict(plan)}, ensure_ascii=True) + "\n").encode("utf-8")
    if len(data) > MAX_PROJECT_BYTES:
        raise ValueError("This plan exceeds the 24 MiB size limit. Try a smaller folder.")
    return _write(plan.protected_root or plan.root, path, PLAN_SUFFIX, data, expected)


def _display_path(path):
    # Quote exact spellings and keep filesystem control characters inert.
    return json.dumps(path, ensure_ascii=False).replace("/", "\\")


def coverage_notes(plan):
    if not (plan.limited or plan.gaps):
        return ["The scan finished within its limits and reported no skipped paths."]
    lines = ["Scan coverage is incomplete."]
    if plan.limited:
        lines.extend([plan.scan_limit, "Unvisited entries beyond the limit are outside the skipped-path count."])
    if plan.gaps:
        lines.extend(["", f"Skipped paths ({len(plan.gaps):,}). A skipped folder can contain additional files."])
        for reason, count in sorted(Counter(plan.gaps.values()).items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"  {count:,} × {reason}")
        lines.extend(["", "Skipped paths relative to the inspected folder"])
        lines.extend(f"- {_display_path(path)}: {reason}" for path, reason in sorted(plan.gaps.items()))
    return lines


def export_text(plan):
    ready, blocked, kept, pending = [], [], [], []
    for source, proposal in plan.proposals().items():
        item = plan.files[source]
        origin = _display_path(source)
        group = f"  [Collection: {item.collection}]" if item.collection else ""
        step = f"{proposal.change}  {origin}  ->  {_display_path(proposal.destination)}{group}"
        if item.decision == "Keep":
            kept.append(origin + group)
        elif item.decision == "Review":
            pending.append(f"{step}  ({proposal.blocker})" if proposal.blocker else step)
        elif proposal.blocker or proposal.change == "No change":
            blocked.append(f"{step}  ({proposal.blocker or 'Already in place.'})")
        else:
            ready.append(step)

    lines = [
        "JOURNEY 1.0 | FOLDER PLAN",
        "",
        f"Source folder: {plan.root}",
        f"Observed at: {plan.scanned_at}",
        "Paths below are relative to the source folder.",
        "This checklist records a scan snapshot. Verify the current files, folders, and dependencies before making manual changes.",
        "",
    ]
    if plan.limited or plan.gaps:
        lines.extend([*coverage_notes(plan), ""])
    for heading, items in (
        ("Included changes", ready),
        ("Included items that need review", blocked),
        ("Keep in place", kept),
        ("Undecided proposals", pending),
    ):
        lines.extend([f"{heading} ({len(items)})", *(f"- {item}" for item in items), ""])
    return "\n".join(lines)


def export_plan(plan, path):
    data = export_text(plan).encode("utf-8", errors="backslashreplace")
    _write(plan.protected_root or plan.root, path, ".txt", data)
