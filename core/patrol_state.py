"""Restart-persistent operator posture; never a managed-mutation grant."""
import json
import sqlite3

DEFAULT = {'lifecycle': 'CONSTRUCTION', 'mode': 'Sweep-and-Build',
           'authority': 'Shadow/explicit approval', 'paused': False}


def validated_state(row):
    """One validator for operator displays and execution-time posture checks."""
    try:
        state = json.loads(row[1])
        if (not isinstance(state, dict) or set(state) != set(DEFAULT)
                or type(state.get('paused')) is not bool):
            raise ValueError('Invalid Patrol control state')
        if any(state.get(key) != DEFAULT[key] for key in ('lifecycle','mode','authority')):
            raise ValueError('Unsupported Gate A posture; no authority expansion permitted')
    except (ValueError, TypeError) as exc:
        return {**DEFAULT, 'paused': True, 'version': row[0],
                'state_integrity': 'REVIEW_REQUIRED', 'reason': str(exc)}
    return {**state, 'version': row[0]}


def read_snapshot(conn):
    """Read only: a missing policy is unknown, never an implicit default grant."""
    try:
        row = conn.execute('SELECT id,state_json FROM patrol_control_events ORDER BY id DESC LIMIT 1').fetchone()
        if row is not None:
            return validated_state(row)
    except sqlite3.Error:
        pass
    return {**DEFAULT, 'paused': True, 'version': None,
            'state_integrity': 'UNKNOWN', 'reason': 'Persisted posture unavailable; no initialization performed'}


def read_state(conn):
    conn.execute('''CREATE TABLE IF NOT EXISTS patrol_control_events (
        id INTEGER PRIMARY KEY, state_json TEXT NOT NULL, reason TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')))''')
    row = conn.execute('SELECT id,state_json FROM patrol_control_events ORDER BY id DESC LIMIT 1').fetchone()
    if row is None:
        conn.execute('INSERT INTO patrol_control_events(state_json,reason) VALUES(?,?)',
                     (json.dumps(DEFAULT), 'Gate A initial posture'))
        conn.commit()
        return read_state(conn)
    return validated_state(row)


def update_state(conn, *, version, paused, reason):
    if type(paused) is not bool or not isinstance(reason, str) or not reason.strip():
        raise ValueError('A boolean paused value and an explicit reason are required')
    read_state(conn)
    conn.execute('BEGIN IMMEDIATE')
    try:
        current = read_state(conn)
        if current['version'] != version:
            raise ValueError('Patrol state changed; refresh before retrying')
        state = {**DEFAULT, 'paused': paused}
        conn.execute('INSERT INTO patrol_control_events(state_json,reason) VALUES(?,?)',
                     (json.dumps(state), reason.strip()))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return read_state(conn)
