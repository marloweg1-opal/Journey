"""Filesystem metadata checks and filename rules shared by Journey surfaces."""

from pathlib import Path
import stat


TEMP_SUFFIXES = {".tmp", ".temp", ".part", ".crdownload", ".download"}
RESERVED_WINDOWS_NAMES = {
    "con", "prn", "aux", "nul",
    "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
    "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
}


def is_link(info):
    return (
        stat.S_ISLNK(info.st_mode)
        or bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    )


def safe_metadata(path, *, read_guard=None):
    # Check ancestors as well as the leaf. This is an observation, not a pinned
    # handle or authorization for a later filesystem operation.
    path = Path(path)
    if read_guard is not None:
        read_guard(path)
    for part in (*reversed(path.parents), path):
        if read_guard is not None:
            read_guard(path)
            read_guard(part)
        info = part.lstat()
        if is_link(info):
            raise ValueError("Reparse/symlink path requires review")
    return info


def signature(info):
    return (info.st_dev, info.st_ino, info.st_mtime_ns)
