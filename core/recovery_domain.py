"""Derivative-only recovery orchestration contract, not retirement authority."""
from dataclasses import dataclass
from enum import IntEnum
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
from core.read_guard import require_path_not_held
from typing import Protocol


class Effort(IntEnum):
    OBSERVE = 0
    VALIDATE = 1
    DIAGNOSE = 2
    SAFE_RECONSTRUCTION = 3
    DEEP_RECOVERY = 4
    MAXIMUM_SAFE_RECOVERY = 5


@dataclass(frozen=True)
class RecoveryAuthority:
    scope: str
    max_effort: Effort = Effort.DIAGNOSE
    derivative_output_authorized: bool = False
    authority_receipt: str = ''
    output_scope: str = ''


class RecoveryProvider(Protocol):
    name: str
    levels: tuple[Effort, ...]

    def attempt(self, source: bytes, level: Effort) -> bytes | None: ...
    def prove_usable(self, candidate: bytes) -> dict: ...


def initialize(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS recovery_attempts (
        id INTEGER PRIMARY KEY, provider TEXT NOT NULL, source_sha256 TEXT NOT NULL,
        effort TEXT NOT NULL, authority_receipt TEXT NOT NULL, state TEXT NOT NULL,
        proof_json TEXT, output_path TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now')))''')


def storage_preflight(output_root, required_bytes):
    """Observe destination capacity, not a reservation or permission to execute."""
    from core.stewardship_contract import assess_resource_feasibility
    try:
        require_path_not_held(output_root)
        from core.media_inventory import safe_metadata
        safe_metadata(output_root, read_guard=require_path_not_held)
        require_path_not_held(output_root)
        free = shutil.disk_usage(output_root).free
        error = None
    except (OSError, ValueError) as exc:
        free, error = None, str(exc)
    result = assess_resource_feasibility({'storage': required_bytes}, {'storage': free})
    result.update({'required_bytes': required_bytes, 'available_bytes': free,
                   'destination': str(output_root), 'capacity_reserved': False})
    if error:
        result['observation_error'] = error
    return result


def recover_derivative(conn, source, output_root, provider, authority, *, max_bytes=16_000_000,
                       storage_margin_bytes=1_000_000):
    """Trusted providers receive immutable bytes, never a source path or delete grant.

    No production repair providers are installed. This bounded orchestrator is
    exercised with disposable providers/fixtures before real repair execution.
    """
    from core.perception_policy import contains
    source, output_root = Path(source), Path(output_root)
    if not contains(authority.scope, str(source)):
        raise PermissionError('Source outside task authority')
    if (authority.derivative_output_authorized is not True
            or not isinstance(authority.authority_receipt, str)
            or not authority.authority_receipt.strip()):
        return {'state':'AWAITING_DERIVATIVE_AUTHORITY','retirement_authorized':False}
    if not authority.output_scope or not contains(authority.output_scope, str(output_root)):
        raise PermissionError('Derivative workspace outside task authority')
    if type(authority.max_effort) is not Effort:
        raise ValueError('A defined recovery Effort ceiling is required')
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError('A positive integer byte budget is required')
    if type(storage_margin_bytes) is not int or storage_margin_bytes < 0:
        raise ValueError('Storage margin must be a nonnegative integer')
    from core.media_inventory import safe_metadata
    try:
        require_path_not_held(source)
        output_info = safe_metadata(output_root, read_guard=require_path_not_held)
        parent_info = safe_metadata(source.parent, read_guard=require_path_not_held)
    except (OSError, ValueError) as exc:
        return {'state':'REVIEW','reason':str(exc),'retirement_authorized':False}
    if not stat.S_ISDIR(output_info.st_mode) or (output_info.st_dev, output_info.st_ino) == (parent_info.st_dev, parent_info.st_ino):
        raise ValueError('A separate existing derivative workspace is required')
    resources = storage_preflight(output_root, max_bytes + storage_margin_bytes)
    if resources['state'] != 'RESOURCE_FEASIBLE':
        return {'state': resources['state'], 'resources': resources, 'retirement_authorized': False}
    from core.recovery_inspection import file_identity
    before = file_identity(source, max_bytes=max_bytes)
    if before is None or before['size'] > max_bytes:
        return {'state':'REVIEW','reason':'Source identity or byte budget not established'}
    from core.media_inventory import safe_metadata
    expected = (before['device'], before['inode'], before['size'], before['mtime_ns'])
    def matches(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) == expected
    try:
        if not matches(safe_metadata(source, read_guard=require_path_not_held)):
            return {'state':'REVIEW','reason':'Source changed before bounded read'}
        require_path_not_held(source)
        with source.open('rb') as stream:
            if not matches(os.fstat(stream.fileno())):
                return {'state':'REVIEW','reason':'Opened source identity changed'}
            require_path_not_held(source)
            data = stream.read(before['size'])
            stable = matches(os.fstat(stream.fileno()))
        if not stable or not matches(safe_metadata(source, read_guard=require_path_not_held)) or len(data) != before['size']:
            return {'state':'REVIEW','reason':'Source changed during bounded read'}
    except (OSError, ValueError):
        return {'state':'REVIEW','reason':'Source unavailable for bounded read'}
    if hashlib.sha256(data).hexdigest() != before['sha256']:
        return {'state':'REVIEW','reason':'Source changed during read'}
    initialize(conn)
    for level in sorted(set(provider.levels)):
        if level < Effort.SAFE_RECONSTRUCTION or level > authority.max_effort:
            continue
        cur = conn.execute('INSERT INTO recovery_attempts(provider,source_sha256,effort,authority_receipt,state) VALUES(?,?,?,?,?)',
            (provider.name,before['sha256'],level.name,authority.authority_receipt,'RUNNING'))
        conn.commit()
        attempt_id = cur.lastrowid
        try:
            require_path_not_held(source)
            candidate = provider.attempt(data,level)
            proof = provider.prove_usable(candidate) if isinstance(candidate,bytes) and 0 < len(candidate) <= max_bytes else {'usable':False,'reason':'No bounded output'}
            if file_identity(source, max_bytes=max_bytes) != before:
                raise RuntimeError('Source identity changed; stop recovery')
            if proof.get('usable') is not True or not proof.get('checks') or any(value is not True for value in proof['checks'].values()):
                conn.execute("UPDATE recovery_attempts SET state='REJECTED',proof_json=? WHERE id=?",(json.dumps(proof),attempt_id))
                conn.commit()
                continue
            output = output_root / f'recovery-{attempt_id}-{before["sha256"][:12]}.bin'
            resources = storage_preflight(output_root, len(candidate) + storage_margin_bytes)
            if resources['state'] != 'RESOURCE_FEASIBLE':
                conn.execute("UPDATE recovery_attempts SET state=?,proof_json=? WHERE id=?",
                             (resources['state'], json.dumps({'proof': proof, 'resources': resources}), attempt_id))
                conn.commit()
                return {'state': resources['state'], 'resources': resources,
                        'attempt_id': attempt_id, 'retirement_authorized': False}
            conn.execute("UPDATE recovery_attempts SET state='WRITING_DERIVATIVE',output_path=?,proof_json=? WHERE id=?",(str(output),json.dumps(proof),attempt_id))
            conn.commit()
            require_path_not_held(output)
            with output.open('xb') as stream:
                stream.write(candidate)
                stream.flush()
                os.fsync(stream.fileno())
            output_identity = file_identity(output, max_bytes=max_bytes)
            if output_identity is None or output_identity['sha256'] != hashlib.sha256(candidate).hexdigest():
                raise RuntimeError('Derivative write verification failed')
            conn.execute("UPDATE recovery_attempts SET state='VERIFIED' WHERE id=?",(attempt_id,))
            conn.commit()
            return {'state':'VERIFIED','output':str(output),'attempt_id':attempt_id,'proof':proof,'retirement_authorized':False}
        except Exception as exc:
            conn.execute("UPDATE recovery_attempts SET state='MANUAL_RECOVERY_REQUIRED',proof_json=? WHERE id=?",(json.dumps({'error':str(exc)}),attempt_id))
            conn.commit()
            return {'state':'MANUAL_RECOVERY_REQUIRED','attempt_id':attempt_id,'retirement_authorized':False}
    return {'state':'NO_PROVEN_RECOVERY','retirement_authorized':False}


def capability_status():
    return {'domain':'Recovery & Repair','effort_levels':[level.name for level in Effort],
            'patrol_mode':'structural_observation_only','task_mode':'bounded_derivative_contract',
            'production_repair_providers':[], 'originals':'immutable_by_default',
            'retirement_authority':False, 'semantic_providers_enabled':False}


def observe(path, size):
    from core.media_recovery import VIDEO, PHOTO
    return {'domain':'Recovery & Repair', 'effort':'OBSERVE',
            'state':'SUSPECT_EMPTY_MEDIA' if Path(path).suffix.lower() in VIDEO|PHOTO and size==0 else 'NOT_VALIDATED',
            'semantic_inspection':False,'repair_authorized':False}
