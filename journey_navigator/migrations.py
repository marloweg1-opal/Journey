"""Snapshot retained inspections before an additive application migration."""

from pathlib import Path
from contextlib import closing
import sqlite3
from datetime import datetime, timezone

from core.file_paths import safe_metadata


SCHEMA_VERSION = 2


def prepare_patrol_schema(app):
    app.conn.execute('CREATE TABLE IF NOT EXISTS navigator_schema(version INTEGER PRIMARY KEY,backup TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP)')
    row=app.conn.execute('SELECT max(version) FROM navigator_schema').fetchone()[0]
    if row is not None and row>SCHEMA_VERSION:
        raise ValueError('This Navigator data was created by a newer version. Open that version to review it.')
    if row==SCHEMA_VERSION:
        return
    folder=app.data_dir/'checkpoints'
    folder.mkdir(exist_ok=True)
    safe_metadata(folder)
    target=folder/('before-registry-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.sqlite')
    app.conn.commit()
    with closing(sqlite3.connect(target)) as backup:
        app.conn.backup(backup)
        if backup.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise ValueError('The pre-upgrade checkpoint failed its integrity check.')
    with app.conn:
        app.conn.execute('INSERT INTO navigator_schema(version,backup) VALUES(?,?)',(SCHEMA_VERSION,str(target)))


def checkpoints(app):
    return [dict(row) for row in app.conn.execute('SELECT version,backup,created FROM navigator_schema ORDER BY version DESC') if Path(row['backup']).is_file()]


def restore_inspection(app_data, selected):
    """Restore only inspection state. Action history stays current and scopes need reselection."""
    data=Path(app_data)
    selected=Path(selected)
    if selected.parent!=data/'checkpoints':
        raise ValueError('Choose a Journey inspection checkpoint.')
    safe_metadata(selected)
    database=data/'navigator-inspection.sqlite'
    source=sqlite3.connect(selected.as_uri()+'?mode=ro',uri=True)
    try:
        if source.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise ValueError('The chosen recovery snapshot is invalid.')
        recovery=data/'checkpoints'/('recovery-before-restore-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.sqlite')
        with closing(sqlite3.connect(database)) as current, closing(sqlite3.connect(recovery)) as preserved:
            current.backup(preserved)
            source.backup(current)
            tables={row[0] for row in current.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
            if 'scope_access' in tables:
                current.execute('UPDATE scope_access SET inspect=0,propose=0')
            if 'destinations' in tables:
                current.execute("UPDATE destinations SET state='Paused',reason='Recovery restored. Reselect and authorize each scope.'")
            current.commit()
    finally:
        source.close()


def clear_inspection_backups(data):
    folder=Path(data)/'checkpoints'
    if not folder.exists():
        return
    safe_metadata(folder)
    for pattern in ('before-patrol-*.sqlite','before-registry-*.sqlite','recovery-before-restore-*.sqlite'):
        for path in folder.glob(pattern):
            safe_metadata(path)
            path.unlink()
