"""Deny-only source-hold evaluation. NOT_HELD never grants read authority."""
import ntpath
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ReadDecision:
    state: str
    reason: str


def _local_path(value):
    value = str(value).replace('/', '\\')
    drive, tail = ntpath.splitdrive(value)
    if (len(drive) != 2 or drive[1] != ':' or not drive[0].isascii()
            or not drive[0].isalpha() or not tail.startswith('\\')
            or ':' in tail or '\x00' in value):
        raise ValueError('Absolute local drive path required; aliases need review')
    if any(part.endswith((' ', '.')) and part not in ('.', '..')
           for part in tail.split('\\') if part):
        raise ValueError('Ambiguous Windows path spelling')
    return ntpath.normpath(value).casefold()


def evaluate(conn, path):
    """Consult the complete hold set before any target filesystem operation."""
    try:
        target = _local_path(path)
    except (ValueError, TypeError):
        return ReadDecision('UNSUPPORTED_PATH', 'Unsupported or ambiguous path')
    try:
        holds = []
        for scope, reason in conn.execute('SELECT scope,reason FROM media_source_holds'):
            if not isinstance(scope, str) or not isinstance(reason, str) or not reason.strip():
                raise ValueError('Invalid hold record')
            holds.append((_local_path(scope), reason))
    except (sqlite3.Error, ValueError, TypeError):
        return ReadDecision('POLICY_UNAVAILABLE', 'Source-hold policy could not be verified')
    for scope, reason in holds:
        if target == scope or target.startswith(scope.rstrip('\\') + '\\'):
            return ReadDecision('SOURCE_HELD', reason)
    return ReadDecision('NOT_HELD', 'No matching hold; other read controls still required')


def evaluate_store(store, path):
    """Open a trusted application-supplied policy store without creating it."""
    try:
        uri = Path(store).absolute().as_uri() + '?mode=ro'
        conn = sqlite3.connect(uri, uri=True, timeout=0.1)
        try:
            return evaluate(conn, path)
        finally:
            conn.close()
    except (sqlite3.Error, OSError, ValueError):
        return ReadDecision('POLICY_UNAVAILABLE', 'Source-hold store unavailable')


def require_not_held(conn, path):
    decision = evaluate(conn, path)
    if decision.state == 'UNSUPPORTED_PATH':
        raise ValueError(f'{decision.state}: {decision.reason}')
    if decision.state != 'NOT_HELD':
        raise PermissionError(f'{decision.state}: {decision.reason}')


def require_path_not_held(path):
    """Application-owned store, never a caller-supplied policy override."""
    store = Path(__file__).parent.parent / 'private' / 'media_recovery' / 'inventory-v2.sqlite'
    decision = evaluate_store(store, path)
    if decision.state != 'NOT_HELD':
        raise PermissionError(f'{decision.state}: {decision.reason}')
