"""Shared read-only work-policy projection and exact-language draft interpretation.

This is not a second policy store, a permission evaluator, or an approval path.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
from datetime import datetime, timezone

from core.patrol_state import read_snapshot


REQUESTS = {
    'pause journey': {'paused': True},
    'resume journey': {'paused': False},
    'only help with duplicate detection, and ask before every job': {'focus': ['duplicate_detection'], 'approval_mode': 'Ask First'},
    'only help with duplicate detection and ask before every job': {'focus': ['duplicate_detection'], 'approval_mode': 'Ask First'},
    'ask before every job': {'approval_mode': 'Ask First'},
    'observe only': {'work_mode': 'Observe'},
    'use balanced mode': {'work_mode': 'Balanced'},
}


def view(conn):
    state = read_snapshot(conn)
    known = state.get('state_integrity') not in ('UNKNOWN', 'REVIEW_REQUIRED')
    return {'posture': state, 'available': known,
            'effective_mode': ('Paused' if state['paused'] else 'Legacy Gate A posture') if known else 'Unknown',
            'source': 'patrol_control_events', 'observed_at': datetime.now(timezone.utc).isoformat(),
            'implemented_controls': ['paused'],
            'unsupported_modes': ['Observe', 'Ask First', 'Balanced', 'Focused'],
            'permission_granted': False,
            'limitations': ['This is persisted policy, not proof of worker liveness',
                           'Pause applies at existing worker boundaries; it does not cancel in-flight operations',
                           'Task approval, registered scopes, source holds and Gates remain separate checks',
                           'Legacy posture is not a claim that every new job requires foreground approval']}


def preview(conn, intention):
    if type(intention) is not str or not 1 <= len(intention.strip()) <= 1000:
        raise ValueError('Intention must be 1..1000 characters')
    current = view(conn)
    key = ' '.join(intention.casefold().strip().rstrip('.!?').split())
    requested = REQUESTS.get(key)
    if requested is None:
        return {'recognized': False, 'current': current, 'applied': False, 'permission_granted': False}
    draft = {'intention': intention.strip(), 'requested': json.loads(json.dumps(requested)),
             'based_on_version': current['posture']['version'],
             'based_on_posture': current['posture']}
    digest = hashlib.sha256(json.dumps(draft, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    unsupported = [key for key in requested if key != 'paused']
    return {'recognized': True, 'current': current, 'draft': draft, 'review_digest': digest,
            'state': 'BLOCKED' if not current['available'] else 'UNSUPPORTED' if unsupported else 'REVIEW_REQUIRED',
            'unsupported_fields': unsupported, 'applied': False, 'permission_granted': False,
            'reason': 'Preview only. No confirmation, persistence or execution authorization occurs here.',
            'next_step': 'Use existing reviewed pause control' if not unsupported and current['available'] else
                         'Worker enforcement and exact foreground confirmation are prerequisites; requested restrictions are not active'}


def inspect_store(ledger, intention=None):
    conn = sqlite3.connect(Path(ledger).absolute().as_uri() + '?mode=ro', uri=True, timeout=1)
    try:
        return view(conn) if intention is None else preview(conn, intention)
    finally:
        conn.close()
