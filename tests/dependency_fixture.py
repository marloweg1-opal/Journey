"""Explicit in-memory dependency grants for disposable test roots only."""
import sqlite3
import tempfile
from pathlib import Path
from core.dependency_evidence import inspect_references as inspect
from core.perception_policy import set_policy


def inspect_references(targets, roots, **budgets):
    roots = list(roots)
    temp = Path(tempfile.gettempdir()).absolute()
    conn = sqlite3.connect(':memory:')
    try:
        for root in roots:
            path = Path(root).absolute()
            if path == temp or not path.is_relative_to(temp):
                raise ValueError('Dependency fixture grants require a disposable temp scope')
            set_policy(conn, str(path), 'LIMITED', reason='disposable test fixture',
                       purposes=('dependency_inspection',), retention=True)
        return inspect(targets, roots, privacy_conn=conn, **budgets)
    finally:
        conn.close()
