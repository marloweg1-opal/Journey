"""Snapshot retained inspections before an additive application migration."""

from pathlib import Path
import sqlite3
from datetime import datetime, timezone

from core.file_paths import safe_metadata


def prepare_patrol_schema(app):
    app.conn.execute('CREATE TABLE IF NOT EXISTS navigator_schema(version INTEGER PRIMARY KEY,backup TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP)')
    row=app.conn.execute('SELECT max(version) FROM navigator_schema').fetchone()[0]
    if row is not None and row>1:
        raise ValueError('This Navigator data was created by a newer version. Open that version to review it.')
    if row==1:
        return
    folder=app.data_dir/'checkpoints'
    folder.mkdir(exist_ok=True)
    safe_metadata(folder)
    target=folder/('before-patrol-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.sqlite')
    app.conn.commit()
    with sqlite3.connect(target) as backup:
        app.conn.backup(backup)
        if backup.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise ValueError('The pre-upgrade checkpoint failed its integrity check.')
    with app.conn:
        app.conn.execute('INSERT INTO navigator_schema(version,backup) VALUES(1,?)',(str(target),))


def checkpoints(app):
    return [dict(row) for row in app.conn.execute('SELECT version,backup,created FROM navigator_schema ORDER BY version DESC')]
