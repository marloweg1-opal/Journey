import sqlite3
from pathlib import Path

conn = sqlite3.connect(Path(__file__).with_name('ark.sqlite'))
print(conn.execute("SELECT sql FROM sqlite_master WHERE name='files';").fetchone()[0])
