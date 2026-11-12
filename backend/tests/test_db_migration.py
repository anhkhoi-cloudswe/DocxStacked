import shutil
import sqlite3
from pathlib import Path
import pytest

from backend.app.core.config import get_settings


def test_legacy_db_migration(tmp_path: Path, monkeypatch):
    """
    Verify automatic migration from gomde.db to docxstacked.db without losing data.
    """
    storage_dir = tmp_path / "data"
    storage_dir.mkdir(parents=True, exist_ok=True)

    old_db = storage_dir / "gomde.db"
    new_db = storage_dir / "docxstacked.db"

    # 1. Create a dummy legacy gomde.db with sample data
    conn = sqlite3.connect(str(old_db))
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE subjects (code TEXT PRIMARY KEY, name TEXT)")
    cursor.execute("INSERT INTO subjects (code, name) VALUES ('CSD202', 'Data Structures and Algorithms')")
    cursor.execute("CREATE TABLE questions (id INTEGER PRIMARY KEY, q_index INTEGER)")
    cursor.execute("INSERT INTO questions (id, q_index) VALUES (1, 1), (2, 2)")
    conn.commit()
    conn.close()

    assert old_db.exists()
    assert not new_db.exists()

    # 2. Run migration function
    from backend.app.db.session import check_and_migrate_legacy_db

    migrated = check_and_migrate_legacy_db(storage_dir=storage_dir, target_db=new_db)
    assert migrated is True

    # 3. Assert new_db exists and has identical data
    assert new_db.exists()
    assert new_db.stat().st_size > 0

    new_conn = sqlite3.connect(str(new_db))
    new_cur = new_conn.cursor()
    new_cur.execute("SELECT code, name FROM subjects")
    rows = new_cur.fetchall()
    assert len(rows) == 1
    assert rows[0] == ("CSD202", "Data Structures and Algorithms")

    new_cur.execute("SELECT COUNT(*) FROM questions")
    q_count = new_cur.fetchone()[0]
    assert q_count == 2
    new_conn.close()
