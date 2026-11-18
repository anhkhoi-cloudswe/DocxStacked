import sqlite3
import os
from pathlib import Path

def main():
    conn = sqlite3.connect("data/docxstacked.db")
    cursor = conn.cursor()
    tables = [r[0] for r in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    print("Tables:", tables)

    # find subject id for PRN232
    subj = cursor.execute("SELECT id, code, name FROM subjects WHERE code='PRN232'").fetchone()
    print("Subject PRN232:", subj)
    if subj:
        subj_id = subj[0]
        rows = cursor.execute("SELECT id, subject_id, exam_type, term, title, url, question_count, status, raw_folder FROM exams WHERE subject_id=?", (subj_id,)).fetchall()
        print(f"\n=== DB EXAMS FOR PRN232 (subject_id={subj_id}) ===")
        for r in rows:
            print(f"ID: {r[0]} | Type: {r[2]} | Term: {r[3]} | Title: {r[4]} | URL: {r[5]} | Q_Count: {r[6]} | Status: {r[7]} | Folder: {r[8]}")
    
    print("\n=== FILES ON DISK IN data/output/PRN232 ===")
    out_dir = Path("data/output/PRN232")
    if out_dir.exists():
        for p in out_dir.glob("*"):
            print(f"{p.name} ({p.stat().st_size} bytes)")
    else:
        print("data/output/PRN232 does not exist")

    print("\n=== RAW FOLDERS IN data/raw/PRN232 ===")
    raw_dir = Path("data/raw/PRN232")
    if raw_dir.exists():
        for p in raw_dir.glob("*"):
            if p.is_dir():
                files = list(p.glob("*"))
                print(f"{p.name}: {len(files)} files")
    else:
        print("data/raw/PRN232 does not exist")

if __name__ == "__main__":
    main()
