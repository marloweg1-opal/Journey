"""Read link records without asking the shell to open or repair them."""

from dataclasses import asdict, dataclass, field
from hashlib import sha256
import ntpath
import os
from pathlib import Path, PureWindowsPath
import re
import sqlite3
import stat
from struct import unpack_from
from uuid import UUID

from core.file_paths import is_link, safe_metadata, signature
from journey_planner.catalog import absolute_path, check_local_drive


LINK_SIZE = 1024 * 1024
MAX_HOPS = 24
CLASS_ID = UUID("00021401-0000-0000-c000-000000000046").bytes_le
SYSTEM_ROOTS = {"windows", "program files", "program files (x86)", "programdata",
                "system volume information", "$recycle.bin", "mini_ark"}


class UnsupportedLink(ValueError):
    pass


class ProtectedPath(PermissionError):
    pass


def _integer(data, offset, code="I"):
    size = 2 if code == "H" else 4
    if offset < 0 or offset + size > len(data):
        raise UnsupportedLink("The Windows shortcut is incomplete or damaged.")
    return unpack_from("<" + code, data, offset)[0]


def _string(data, offset, minimum, unicode):
    if not minimum <= offset < len(data):
        raise UnsupportedLink("The Windows shortcut contains an invalid path record.")
    if unicode:
        for end in range(offset, len(data) - 1, 2):
            if data[end:end + 2] == b"\0\0":
                return data[offset:end].decode("utf-16-le")
    else:
        end = data.find(b"\0", offset)
        if end != -1:
            return data[offset:end].decode("mbcs" if os.name == "nt" else "cp1252")
    raise UnsupportedLink("The Windows shortcut contains an unterminated path.")


def shortcut_path(data):
    """Support a local LinkInfo path or a filesystem-relative StringData path."""
    if len(data) < 76 or _integer(data, 0) != 76 or data[4:20] != CLASS_ID:
        raise UnsupportedLink("This file does not contain a readable Windows shortcut.")
    flags = _integer(data, 20)
    offset = 76
    if flags & 1:  # LinkTargetIDList is an opaque shell record.
        offset += 2 + _integer(data, offset, "H")
    base, suffix = "", ""
    if flags & 2:
        size, header = _integer(data, offset), _integer(data, offset + 4)
        if not (header == 28 or header >= 36) or not header <= size <= len(data) - offset:
            raise UnsupportedLink("The Windows shortcut contains invalid destination metadata.")
        info = data[offset:offset + size]
        info_flags = _integer(info, 8)
        if info_flags & 2:
            raise UnsupportedLink("Network shortcuts are outside local inspection.")
        if info_flags & 1:
            base_unicode = _integer(info, 28) if header >= 36 else 0
            suffix_unicode = _integer(info, 32) if header >= 36 else 0
            base = _string(info, base_unicode or _integer(info, 16), header, bool(base_unicode))
            suffix = _string(info, suffix_unicode or _integer(info, 24), header, bool(suffix_unicode))
        offset += size
    if base:
        if suffix and (ntpath.splitdrive(suffix)[0] or suffix.startswith(("\\\\", "//"))):
            raise UnsupportedLink("The Windows shortcut contains an ambiguous destination.")
        return ntpath.join(base, suffix.lstrip("\\/")) if suffix else base
    unicode = bool(flags & 128)
    for bit in (4, 8):
        if flags & bit:
            length = _integer(data, offset, "H") * (2 if unicode else 1)
            offset += 2
            if offset + length > len(data):
                raise UnsupportedLink("The Windows shortcut contains an incomplete relative path.")
            if bit == 8 and length:
                encoding = "utf-16-le" if unicode else ("mbcs" if os.name == "nt" else "cp1252")
                return data[offset:offset + length].decode(encoding)
            offset += length
    raise UnsupportedLink("This shortcut needs Windows Shell tracking or a destination type Journey cannot inspect.")


def path_key(path):
    return os.path.normcase(str(path))


def local_target(value, link, *, reparse=False):
    if not value or "\0" in value:
        raise UnsupportedLink("The link does not contain a usable destination path.")
    if os.name == "nt" or not reparse:
        value = value.replace("/", "\\")
        if reparse and re.match(r"^(?:\\\\\?\\|\\\?\?\\)[A-Za-z]:\\", value):
            value = value[4:]
        drive, tail = ntpath.splitdrive(value)
        if value.startswith("\\") or (drive and (not re.fullmatch(r"[A-Za-z]:", drive) or not tail.startswith("\\"))):
            raise UnsupportedLink("Network, device, and drive-relative links are outside local inspection.")
        if os.name != "nt":
            raise UnsupportedLink("Windows shortcut targets can be inspected on Windows.")
        for part in PureWindowsPath(value).parts:
            if part not in ("..", ".") and part != drive + "\\" and part.endswith((" ", ".")):
                raise UnsupportedLink("The link has an ambiguous Windows folder name.")
    path = Path(value)
    return absolute_path(os.path.normpath(path if path.is_absolute() else link.parent / path))


def kind_of(path, info):
    if getattr(info, "st_reparse_tag", 0) == getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003):
        return "junction"
    if stat.S_ISLNK(info.st_mode):
        return "symbolic link"
    if is_link(info):
        return "unsupported reparse point"
    if stat.S_ISREG(info.st_mode) and path.suffix.casefold() == ".lnk":
        return "Windows shortcut"
    return "folder" if stat.S_ISDIR(info.st_mode) else "file"


def identity(info):
    if not info.st_ino:
        raise UnsupportedLink("This volume did not provide a stable file identity for safe inspection.")
    return f"{info.st_dev}:{info.st_ino}"


class Boundaries:
    def __init__(self, blocked=(), *, hold_store=None, perception_store=None):
        self.blocked = tuple(Path(path) for path in blocked)
        self.hold_store = hold_store
        self.perception_store = perception_store
        self.holds = ()
        self.perception = ()

    @staticmethod
    def _rows(store, query, table, *, optional_table=False):
        if store is None:
            return []
        try:
            safe_metadata(store)
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as error:
            raise ProtectedPath("Journey could not verify its existing source policy.") from error
        try:
            conn = sqlite3.connect(store.as_uri() + "?mode=ro", uri=True, timeout=0.1)
            try:
                if optional_table and not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                    return []
                return conn.execute(query).fetchall()
            finally:
                conn.close()
        except (sqlite3.Error, ValueError) as error:
            raise ProtectedPath("Journey could not verify its existing source policy.") from error

    def refresh(self):
        import json

        try:
            self.holds = tuple(absolute_path(scope) for scope, in self._rows(
                self.hold_store, "SELECT scope FROM media_source_holds", "media_source_holds"))
            records = self._rows(self.perception_store,
                "SELECT scope,mode,permissions_json,purposes_json FROM perception_policy_events ORDER BY id DESC",
                "perception_policy_events", optional_table=True)
            self.perception = tuple(sorted(((absolute_path(scope), mode, json.loads(permissions), json.loads(purposes))
                                           for scope, mode, permissions, purposes in records),
                                          key=lambda item: len(item[0].parts), reverse=True))
        except (TypeError, ValueError) as error:
            raise ProtectedPath("Journey found an invalid source policy record.") from error

    def check(self, path):
        path = absolute_path(path)
        if os.name == "nt" and len(path.parts) > 1 and path.parts[1].casefold() in SYSTEM_ROOTS:
            raise ProtectedPath("This Windows system or production folder is protected.")
        if any(path.is_relative_to(root) for root in self.blocked):
            raise ProtectedPath("This folder belongs to the application or its review storage.")
        if any(path.is_relative_to(root) for root in self.holds):
            raise ProtectedPath("An existing Journey source hold covers this destination.")
        return path

    def check_image(self, path):
        path = self.check(path)
        for scope, mode, permissions, purposes in self.perception:
            if path.is_relative_to(scope):
                if (not isinstance(permissions, dict) or not isinstance(purposes, list)
                    or permissions.get("semantic_retention_permission") is not True
                    or permissions.get("learning_permission") is not True
                    or (mode != "OPEN" and not (mode == "LIMITED" and "visual stewardship" in purposes))):
                    raise ProtectedPath("An existing Journey perception policy restricts this image's analysis or retention.")
                break
        return path


@dataclass
class Resolution:
    selected: str
    status: str
    target: str = ""
    reason: str = ""
    physical_id: str = ""
    hops: list = field(default_factory=list)

    def record(self):
        return asdict(self)


def _read_destination(path, info, kind):
    if kind == "Windows shortcut":
        if info.st_size > LINK_SIZE:
            raise UnsupportedLink("This Windows shortcut exceeds the metadata size limit.")
        with path.open("rb") as stream:
            if signature(os.fstat(stream.fileno())) != signature(info):
                raise UnsupportedLink("The shortcut changed while Journey was reading it.")
            data = stream.read(LINK_SIZE + 1)
        if len(data) != info.st_size:
            raise UnsupportedLink("The shortcut changed while Journey was reading it.")
        raw, fingerprint = shortcut_path(data), sha256(data).hexdigest()
    elif kind in ("junction", "symbolic link"):
        raw = os.readlink(path)
        fingerprint = sha256(raw.encode("utf-8", errors="surrogatepass")).hexdigest()
    else:
        raise UnsupportedLink("This reparse point is unsupported. Journey left its destination untouched.")
    if signature(path.lstat()) != signature(info):
        raise UnsupportedLink("The link changed while Journey was reading it.")
    return local_target(raw, path, reparse=kind != "Windows shortcut"), fingerprint


def resolve_folder(selected, policy, allowed=()):
    """Read pointer metadata in scope and stop before opening an unapproved target."""
    requested = absolute_path(selected)
    candidate, hops, visited = requested, [], set()
    scopes = tuple(Path(root) for root in allowed)
    try:
        for _ in range(MAX_HOPS):
            policy.check(candidate)
            if hops and not any(candidate.is_relative_to(root) for root in scopes):
                return Resolution(str(requested), "approval_required", str(candidate),
                                  "This destination is outside the selected scan scope.", hops=hops)
            check_local_drive(candidate)
            for part in (*reversed(candidate.parents), candidate):
                policy.check(part)
                info = part.lstat()
                kind = kind_of(part, info)
                if kind in ("folder", "file"):
                    continue
                key = identity(info)
                if key in visited:
                    return Resolution(str(requested), "cycle", str(part), "This link chain loops back to an earlier link.", hops=hops)
                visited.add(key)
                destination, fingerprint = _read_destination(part, info, kind)
                hops.append({"link": str(part), "kind": kind, "declared_target": str(destination),
                             "identity": key, "fingerprint": fingerprint})
                candidate = destination / candidate.relative_to(part)
                break
            else:
                if kind != "folder":
                    raise UnsupportedLink("This link points to a file. Choose a folder or a folder shortcut.")
                physical = candidate.resolve(strict=True)
                policy.check(physical)
                check_local_drive(physical)
                if hops and not any(physical.is_relative_to(root) for root in scopes):
                    return Resolution(str(requested), "approval_required", str(physical),
                                      "The physical destination is outside the selected scan scope.", hops=hops)
                return Resolution(str(requested), "ready", str(physical), physical_id=identity(safe_metadata(physical)), hops=hops)
        return Resolution(str(requested), "unsupported", str(candidate), "This link chain exceeds 24 hops.", hops=hops)
    except ProtectedPath as error:
        return Resolution(str(requested), "protected", str(candidate), str(error), hops=hops)
    except (FileNotFoundError, NotADirectoryError):
        return Resolution(str(requested), "broken", str(candidate), "Journey could not find the folder or link destination.", hops=hops)
    except PermissionError:
        return Resolution(str(requested), "inaccessible", str(candidate), "Windows or the filesystem denied access to this folder.", hops=hops)
    except (OSError, ValueError) as error:
        return Resolution(str(requested), "unsupported", str(candidate), str(error), hops=hops)
