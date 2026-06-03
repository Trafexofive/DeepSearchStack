#!/usr/bin/env python3
"""Warehouse backup — nightly SQLite dump via docker cp.

Usage:
    python3 scripts/dss-backup.py                      # backup to default dir
    python3 scripts/dss-backup.py --dir /mnt/backups/   # custom backup dir

Keeps last 7 backups, deletes older ones.
"""
import datetime
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CONTAINER = "dss-knowledge-warehouse"
DB_CONTAINER_PATH = "/app/data/warehouse.db"
BACKUP_DIR = Path(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[1] == '--dir' else Path(os.environ.get("DSS_BACKUP_DIR", os.path.expanduser("~/.dss-backups")))
KEEP_DAYS = 7

def main():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = BACKUP_DIR / f"warehouse-{timestamp}.db"

    # Copy DB from container
    print(f"Copying DB from {CONTAINER}...")
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as tmp:
        tmp_path = tmp.name
    
    result = subprocess.run(
        ["docker", "cp", f"{CONTAINER}:{DB_CONTAINER_PATH}", tmp_path],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        print(f"Error: docker cp failed: {result.stderr}")
        os.unlink(tmp_path)
        sys.exit(1)

    # Get stats
    conn = sqlite3.connect(tmp_path)
    entries = conn.execute("SELECT COUNT(*) FROM content").fetchone()[0]
    size_mb = os.path.getsize(tmp_path) / (1024 * 1024)
    conn.close()
    print(f"  {entries} entries, {size_mb:.1f}MB")

    # Copy to backup location
    shutil.copy2(tmp_path, backup_path)
    os.unlink(tmp_path)
    print(f"  ✓ {backup_path}")

    # Clean old backups
    existing = sorted(BACKUP_DIR.glob("warehouse-*.db"))
    cutoff = time.time() - KEEP_DAYS * 86400
    deleted = 0
    for f in existing:
        if f.stat().st_mtime < cutoff:
            f.unlink()
            deleted += 1

    if deleted:
        print(f"  ✗ {deleted} old backups removed (keeping {KEEP_DAYS}d)")
    print(f"Done. {len([f for f in BACKUP_DIR.glob('warehouse-*.db')])} backups retained.")


if __name__ == "__main__":
    main()
