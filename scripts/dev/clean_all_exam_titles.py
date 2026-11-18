import sys
from pathlib import Path
import re

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.db.session import SyncSessionLocal
from backend.app.db.models import Exam, Subject
from backend.app.api.ingest import clean_exam_title
from backend.app.core.config import get_settings

settings = get_settings()
db = SyncSessionLocal()

print("=== SCANNING DB FOR UNCLEAN EXAM TITLES ===")
all_exams = db.query(Exam).all()
updated_exams = []

for ex in all_exams:
    old_title = ex.title
    cleaned = clean_exam_title(old_title)
    if cleaned != old_title:
        ex.title = cleaned
        updated_exams.append((ex.id, old_title, cleaned))

if updated_exams:
    db.commit()
    print(f"Updated {len(updated_exams)} exam titles in DB:")
    for eid, old, new in updated_exams:
        print(f"  [ID {eid}] '{old}' -> '{new}'")
else:
    print("All DB exam titles are already clean! (0 modified)")

print("\n=== SCANNING data/output FOR UNCLEAN DOCX FILENAMES ===")
out_dir = settings.DATA_DIR / "output"
renamed_files = []
if out_dir.exists():
    for f in out_dir.rglob("*.docx"):
        old_name = f.name
        # Check if contains "Đề Thi FE - " or duplicate subject code
        cleaned_stem = clean_exam_title(f.stem)
        if cleaned_stem != f.stem:
            new_path = f.parent / f"{cleaned_stem}.docx"
            if not new_path.exists():
                f.rename(new_path)
                renamed_files.append((old_name, new_path.name))
            else:
                # If target already exists, remove the duplicate old one
                f.unlink()
                renamed_files.append((old_name, f"DELETED DUPLICATE (kept {new_path.name})"))

if renamed_files:
    print(f"Renamed/Cleaned {len(renamed_files)} docx files on disk:")
    for old, new in renamed_files:
        print(f"  '{old}' -> '{new}'")
else:
    print("All output docx filenames are already clean! (0 modified)")
