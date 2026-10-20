import sqlite3
from pathlib import Path

conn = sqlite3.connect(Path(__file__).with_name('ark.sqlite'))
tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table';").fetchall()
for t in tables:
    print(t[0])
