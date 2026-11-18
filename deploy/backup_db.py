"""Consistent SQLite backup using its online backup API."""
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
source = Path(os.getenv('TICKET_DB', 'data/tickets.db')).resolve()
if not source.is_file():
    raise SystemExit('Database does not exist; check TICKET_DB and working directory.')
folder = source.parent / 'backups'
folder.mkdir(mode=0o700, exist_ok=True)
name = datetime.now(timezone.utc).strftime('tickets-%Y%m%dT%H%M%S%fZ.db')
destination = folder / name
with sqlite3.connect(source) as src, sqlite3.connect(destination) as dst:
    src.backup(dst)
os.chmod(destination, 0o600)
print(destination)
