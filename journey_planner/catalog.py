"""Observe a selected folder and turn user decisions into a reviewable plan."""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
import ntpath
import os
from pathlib import Path, PurePosixPath
import re
import stat
from time import monotonic

from core.file_paths import RESERVED_WINDOWS_NAMES, TEMP_SUFFIXES, is_link, safe_metadata, signature


MAX_ENTRIES = 10_000
MAX_SCAN_SECONDS = 20
MAX_COLLECTIONS = 500
MAX_PROJECT_BYTES = 24 * 1024 * 1024
DECISIONS = ("Review", "Include", "Keep")
_FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_EXTRA_RESERVED = {"conin$", "conout$", "com¹", "com²", "com³", "lpt¹", "lpt²", "lpt³"}


def component(value):
    """Validate a single Windows filename or directory component."""
    if not isinstance(value, str) or not value or value.endswith((" ", ".")) or _FORBIDDEN.search(value):
        raise ValueError("Use one Windows-compatible name without trailing spaces or periods.")
    stem = value.partition(".")[0].rstrip().lower()
    if stem in RESERVED_WINDOWS_NAMES or stem in _EXTRA_RESERVED:
        raise ValueError("That name is reserved by Windows.")
    try:
        length = len(value.encode("utf-16-le")) // 2
    except UnicodeEncodeError as exc:
        raise ValueError("The name contains unsupported characters.") from exc
    if length > 255:
        raise ValueError("A name can contain up to 255 Windows filename characters.")
    return value


def relative_path(value):
    if not isinstance(value, str):
        raise ValueError("Expected a relative file or folder path.")
    for part in value.split("/"):
        component(part)
    return value


def absolute_path(value):
    if not isinstance(value, (str, Path)):
        raise ValueError("Choose an absolute local path.")
    path = Path(value)
    if not path.is_absolute() or "\0" in str(path):
        raise ValueError("Choose an absolute local path.")
    if os.name == "nt":
        if not re.fullmatch(r"[A-Za-z]:", path.drive):
            raise ValueError("Choose a local Windows drive. Network and device paths are unsupported.")
        for part in path.parts[1:]:
            component(part)
    elif ".." in path.parts:
        raise ValueError("Choose a path without parent directory references.")
    return path


def check_local_drive(path):
    if os.name == "nt":
        import ctypes

        if ctypes.windll.kernel32.GetDriveTypeW(str(path.anchor)) not in (2, 3, 5, 6):
            raise ValueError("Choose a folder on a local drive.")


def suggested_name(name):
    """Tidy obvious separators while preserving words, Unicode, and the extension."""
    suffix = PurePosixPath(name).suffix
    if name.startswith(".") or suffix.lower() in TEMP_SUFFIXES:
        return name
    stem = name[:-len(suffix)] if suffix else name
    cleaned = re.sub(r"[ _]+", " ", stem).strip()
    if not cleaned:
        return name
    try:
        return component(cleaned + suffix)
    except ValueError:
        return name


def validate_name(original, name):
    component(name)
    if PurePosixPath(original).suffix.casefold() != PurePosixPath(name).suffix.casefold():
        raise ValueError("Keep the original file extension when proposing a name.")
    return name


@dataclass
class File:
    size: int
    mtime_ns: int
    name: str
    collection: str = ""
    decision: str = "Review"


@dataclass(frozen=True)
class Proposal:
    destination: str
    change: str
    blocker: str = ""


@dataclass
class Plan:
    root: str
    scanned_at: str
    files: dict[str, File] = field(default_factory=dict)
    directories: list[str] = field(default_factory=list)
    gaps: dict[str, str] = field(default_factory=dict)
    limited: bool = False
    collections: list[str] = field(default_factory=list)

    def add_collection(self, label):
        label = component(label.strip())
        if len(self.collections) >= MAX_COLLECTIONS:
            raise ValueError(f"A plan can contain up to {MAX_COLLECTIONS} collections.")
        if label.casefold() in {name.casefold() for name in self.collections}:
            raise ValueError("A collection with that name already exists.")
        self.collections.append(label)
        return label

    def assign(self, paths, collection):
        if collection and collection not in self.collections:
            raise ValueError("Choose a collection first.")
        changed = False
        for path in paths:
            item = self.files[path]
            if item.collection != collection:
                item.collection = collection
                item.decision = "Review"
                changed = True
        return changed

    def rename(self, path, name):
        item = self.files[path]
        name = validate_name(path, name)
        if name == item.name:
            return False
        item.name = name
        item.decision = "Review"
        return True

    def proposals(self):
        destinations = {}
        folder_spellings = {name.casefold(): name for name in self.directories}
        for source, item in self.files.items():
            original = PurePosixPath(source)
            if item.collection:
                folder = folder_spellings.get(item.collection.casefold(), item.collection)
                target = PurePosixPath(folder, item.name)
            else:
                target = original.with_name(item.name)
            destinations[source] = target.as_posix()

        occupied = Counter(path.casefold() for path in self.files)
        occupied.update(path.casefold() for path in self.directories)
        included = Counter(
            destinations[path].casefold() for path, item in self.files.items()
            if item.decision == "Include" and destinations[path] != path
        )
        occupied_folders = {path.casefold() for path in self.directories}
        held = {path.casefold() for path in self.gaps}
        results = {}
        for source, target in destinations.items():
            old, new = PurePosixPath(source), PurePosixPath(target)
            move = old.parent != new.parent
            rename = old.name != new.name
            change = "Move and rename" if move and rename else "Move" if move else "Rename" if rename else "No change"
            blocker = ""
            key = target.casefold()
            parents = [part.as_posix().casefold() for part in new.parents]
            projected = ntpath.join(self.root, *new.parts)
            if change != "No change":
                if self.limited:
                    blocker = "Scan limit reached. Verify a smaller folder before planning changes."
                elif old.suffix.lower() in TEMP_SUFFIXES:
                    blocker = "Temporary or incomplete file."
                elif key in held or held.intersection(parents):
                    blocker = "Destination crosses an uninspected path."
                elif key == source.casefold():
                    blocker = "Case-only rename needs manual review."
                elif occupied[key]:
                    blocker = "Destination already exists in the scan."
                elif any(occupied[parent] and parent not in occupied_folders for parent in parents):
                    blocker = "A file occupies a proposed destination folder."
                elif included[key] > int(self.files[source].decision == "Include"):
                    blocker = "More than one included file uses this destination."
                elif len(projected.encode("utf-16-le")) // 2 > 259:
                    blocker = "Proposed path exceeds the standard Windows path limit."
            results[source] = Proposal(target, change, blocker)
        return results


def scan_folder(folder, *, max_entries=MAX_ENTRIES, max_seconds=MAX_SCAN_SECONDS):
    root = absolute_path(folder)
    check_local_drive(root)
    if not stat.S_ISDIR(safe_metadata(root).st_mode):
        raise ValueError("Choose a folder rather than a file.")
    root = root.resolve(strict=True)
    check_local_drive(root)
    plan = Plan(str(root), datetime.now(timezone.utc).isoformat(timespec="seconds"))
    pending = [root]
    entries_seen = 0
    deadline = monotonic() + max_seconds

    while pending:
        folder = pending.pop()
        relative = folder.relative_to(root).as_posix()
        observed_files, child_folders = {}, []
        try:
            before = safe_metadata(folder)
            with os.scandir(folder) as entries:
                for entry in entries:
                    entries_seen += 1
                    if entries_seen > max_entries or monotonic() >= deadline:
                        plan.limited = True
                        break
                    path = Path(entry.path)
                    key = path.relative_to(root).as_posix()
                    try:
                        relative_path(key)
                        info = entry.stat(follow_symlinks=False)
                    except (OSError, ValueError):
                        plan.gaps[key] = "Name or metadata could not be read as a Windows-compatible entry."
                        continue
                    if is_link(info):
                        plan.gaps[key] = "Link, junction, or reparse point skipped."
                    elif stat.S_ISDIR(info.st_mode):
                        child_folders.append(path)
                    elif stat.S_ISREG(info.st_mode):
                        observed_files[key] = File(info.st_size, info.st_mtime_ns, suggested_name(path.name))
                    else:
                        plan.gaps[key] = "Special filesystem entry skipped."
            if signature(safe_metadata(folder)) != signature(before):
                raise ValueError("Folder changed during the scan.")
        except (OSError, ValueError):
            if folder == root:
                raise ValueError("The selected folder could not be read reliably. Choose it again.") from None
            plan.gaps[relative] = "Folder was inaccessible or changed during the scan."
        else:
            plan.files.update(observed_files)
            plan.directories.extend(path.relative_to(root).as_posix() for path in child_folders)
            pending.extend(child_folders)
        if plan.limited:
            break
        if pending and monotonic() >= deadline:
            plan.limited = True
            break

    plan.files = dict(sorted(plan.files.items(), key=lambda item: (item[0].casefold(), item[0])))
    plan.directories.sort()
    return plan
