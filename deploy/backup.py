#!/usr/bin/python3
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3

os.umask(0o077)
folder = Path('/var/lib/saoke/backups')
folder.mkdir(exist_ok=True)
target = folder / (datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S') + '.sqlite3')
source = sqlite3.connect('/var/lib/saoke/saoke.sqlite3')
destination = sqlite3.connect(str(target))
try:
    source.backup(destination)
finally:
    destination.close()
    source.close()
for old in sorted(folder.glob('*.sqlite3'), reverse=True)[7:]:
    old.unlink()
print('Database backup completed.')
