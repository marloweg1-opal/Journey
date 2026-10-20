"""Bounded reference evidence. A negative search is never global clearance."""
import hashlib
import math
import time
import os
import stat
import sqlite3
from pathlib import Path, PureWindowsPath
from core.patrol import live_discover
from core.reference_formats import structured_references, STRUCTURED_EXTENSIONS
from core.media_inventory import safe_metadata
from core.read_guard import require_path_not_held

TEXT_EXTENSIONS={'.ini','.json','.toml','.yaml','.yml','.xml','.cfg','.conf','.lua','.ps1','.js','.css','.html','.htm','.md','.url'}


def inspect_references(targets, roots, *, max_files=100, max_bytes=2_000_000, max_seconds=5,
                       privacy_conn=None):
    if any(type(value) is not int or value <= 0 for value in (max_files, max_bytes)):
        raise ValueError('Positive integer dependency count and byte budgets required')
    try:
        valid_time = type(max_seconds) in (int, float) and math.isfinite(max_seconds) and max_seconds > 0
    except OverflowError:
        valid_time = False
    if not valid_time:
        raise ValueError('A finite positive dependency time budget is required')
    started=time.monotonic()
    references=[]
    errors=[]
    checked=[]
    remaining=max_bytes
    coverage=[]
    structured=[]
    def check_privacy(path):
        if privacy_conn is None:
            raise PermissionError('PRIVACY_POLICY_UNAVAILABLE')
        if privacy_conn is not None:
            from core.perception_policy import effective_policy
            try:
                policy = effective_policy(privacy_conn, path, purpose='dependency_inspection')
            except (sqlite3.Error, ValueError, TypeError, AttributeError) as exc:
                raise PermissionError('PRIVACY_POLICY_UNAVAILABLE') from exc
            if (policy['inspection_permission'] != 'SEMANTIC_ALLOWED'
                    or policy['semantic_retention_permission'] is not True):
                raise PermissionError('PRIVACY_DENIED: dependency inspection and retained evidence require explicit policy')
    for root in roots:
        if len(checked)>=max_files or time.monotonic()-started>=max_seconds:
            errors.append({'scope':str(root),'reason':'budget_exhausted'})
            break
        rows,discovery=live_discover(str(root),max_files=max_files-len(checked),max_seconds=max(0.01,max_seconds-(time.monotonic()-started)))
        root_coverage = {'scope':str(root), **discovery, 'content_inspection_complete': False}
        coverage.append(root_coverage)
        errors_before = len(errors)
        for row in rows:
            path=Path(row['canonical_path'])
            if path.suffix.lower() not in TEXT_EXTENSIONS:
                continue
            if remaining<=0 or len(checked)>=max_files or time.monotonic()-started>=max_seconds:
                errors.append({'path':str(path),'reason':'budget_exhausted'})
                break
            try:
                check_privacy(path)
                before=safe_metadata(path, read_guard=require_path_not_held)
                if not stat.S_ISREG(before.st_mode):
                    raise ValueError('Regular configuration file required')
                if before.st_size>min(remaining,256_000):
                    errors.append({'path':str(path),'reason':'file_size_budget'})
                    continue
                require_path_not_held(path)
                check_privacy(path)
                with path.open('rb') as stream:
                    opened=os.fstat(stream.fileno())
                    keys=('st_dev','st_ino','st_size','st_mtime_ns')
                    if any(getattr(before,k)!=getattr(opened,k) for k in keys):
                        raise ValueError('Configuration replaced before read')
                    require_path_not_held(path)
                    check_privacy(path)
                    data=stream.read(min(remaining,256_000))
                    remaining-=len(data)  # Failed decoding/drift still consumed read resources.
                    finished=os.fstat(stream.fileno())
                after=safe_metadata(path, read_guard=require_path_not_held)
                if any(getattr(before,k)!=getattr(after,k) or getattr(opened,k)!=getattr(finished,k) for k in keys) or len(data)!=before.st_size:
                    errors.append({'path':str(path),'reason':'changed_during_read'})
                    continue
                decoded=data.decode('utf-16' if data.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig',errors='strict')
                check_privacy(path)
                text=decoded.casefold()
                fingerprint=hashlib.sha256(data).hexdigest()
                literals, parse_errors=structured_references(path,decoded)
                # Parsing may outlive the grant; recheck before retaining evidence.
                check_privacy(path)
                if privacy_conn is None:
                    structured.extend({'reference':str(path),'fingerprint':fingerprint,**literal} for literal in literals)
                errors.extend({'path':str(path),'reason':'parse_error' if privacy_conn is not None else 'parse: '+error} for error in parse_errors)
                checked.append({'path':str(path),'fingerprint':fingerprint,
                    'reference_method': 'STRUCTURED_LITERALS_AND_TEXT_MATCHING'
                        if path.suffix.lower() in STRUCTURED_EXTENSIONS else 'TEXT_MATCHING_ONLY',
                    'structured_parser_supported': path.suffix.lower() in STRUCTURED_EXTENSIONS,
                    'dependency_semantics_complete': False})
                for target in targets:
                    normalized=str(PureWindowsPath(target)).casefold()
                    forms={normalized,normalized.replace('\\','/'),normalized.replace('\\','\\\\')}
                    match='explicit_path' if any(form in text for form in forms) else 'basename_only' if PureWindowsPath(target).name.casefold() in text else None
                    if match:
                        references.append({'target':target,'reference':str(path),'match':match,'fingerprint':fingerprint})
                    for literal in literals:
                        resolved=literal.get('resolved','').casefold()
                        if resolved==normalized and match!='explicit_path':
                            reference = {'target':target,'reference':str(path),'match':'resolved_literal',
                                         'fingerprint':fingerprint}
                            if privacy_conn is None:
                                reference['field'] = literal['field']
                            references.append(reference)
            except (OSError,UnicodeError,ValueError,RecursionError) as exc:
                reason = str(exc)
                if privacy_conn is not None:
                    # Parser/codec exception text may quote source content.
                    reason = next((code for code in ('PRIVACY_DENIED', 'PRIVACY_POLICY_UNAVAILABLE',
                        'SOURCE_HELD', 'POLICY_UNAVAILABLE', 'UNSUPPORTED_PATH')
                        if reason.startswith(code)), 'inspection_failed')
                errors.append({'path':str(path),'reason':reason})
        root_coverage['content_inspection_complete'] = bool(discovery.get('complete')) and len(errors) == errors_before
    observations = [{'target':target, 'evidence_source':'bounded_configuration_inspection',
        'reference_observation':'REFERENCE_FOUND' if any(r['target']==target for r in references)
          else 'NO_REFERENCE_FOUND_WITHIN_BOUNDED_SEARCH',
        'dependency_state':'UNKNOWN', 'search_performed':bool(checked),
        'exhaustive_domain_proof':False} for target in targets]
    return {'references':references,'checked':checked,'errors':errors,'scope_coverage':coverage,
            'target_observations':observations,
            'structured_candidates':structured,'dependency_state':'UNKNOWN',
            'dependency_clearance':False,
            'reason':'Bounded text search excludes registry, binary, dynamic and unregistered references; absence of matches is not clearance.',
            'bytes_read':max_bytes-remaining}
