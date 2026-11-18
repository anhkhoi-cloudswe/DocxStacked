import sys
from pathlib import Path
import urllib.request
import json
from docx import Document

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.db.session import SyncSessionLocal
from backend.app.db.models import Exam, Subject, ExamType
from backend.app.core.config import get_settings
from backend.app.modules.export.docx_builder import format_exam_docx_filename

settings = get_settings()
db = SyncSessionLocal()
subj = db.query(Subject).filter(Subject.code == 'PRN232').first()
out_dir = settings.DATA_DIR / 'output' / 'PRN232'

print("=== PRN232 FE EXAMS STATUS (DB & DISK) ===")
fe_exams = db.query(Exam).filter(Exam.subject_id == subj.id, Exam.exam_type == ExamType.FE).all()
print(f"Total FE exams in DB: {len(fe_exams)}")

for ex in fe_exams:
    expected_filename = format_exam_docx_filename("PRN232", ex)
    expected_path = out_dir / expected_filename
    
    exact_exists = expected_path.exists()
    exact_size = expected_path.stat().st_size if exact_exists else 0
    
    clean_ex_name = "".join(c for c in expected_filename.replace(".docx", "") if c.isalnum()).lower()
    matching_files = []
    if out_dir.exists():
        for p in out_dir.glob("*.docx"):
            clean_p = "".join(c for c in p.stem if c.isalnum()).lower()
            if clean_ex_name == clean_p:
                matching_files.append((p.name, p.stat().st_size))
                
    print(f"\n[ID {ex.id}] {ex.title}")
    print(f"  - DB Status: {ex.status.value}")
    print(f"  - Question count in DB: {ex.question_count}")
    print(f"  - Term: {ex.term}")
    print(f"  - Expected docx: {expected_filename}")
    print(f"  - Exact file exists: {exact_exists} (size: {exact_size:,} bytes)")
    print(f"  - Normalized matched files: {matching_files}")
    
    if exact_exists or matching_files:
        print(f"  - Tab Soạn đề status: Đã soạn (file tồn tại trên ổ đĩa)")
        print(f"  - Tab Đã soạn status: HIỂN THỊ")
    else:
        if ex.status.value == "crawled":
            print(f"  - Tab Soạn đề status: Chưa có file (DB có bản ghi nhưng file bị xoá/thiếu)")
        else:
            print(f"  - Tab Soạn đề status: Chưa soạn (chưa crawl/biên soạn)")
        print(f"  - Tab Đã soạn status: BỊ ẨN vì không có file docx trên ổ đĩa")

print("\n=== VERIFY /api/user/documents (TAB ĐÃ SOẠN) ===")
req = urllib.request.Request("http://127.0.0.1:8000/api/user/documents")
with urllib.request.urlopen(req) as resp:
    docs = json.loads(resp.read().decode())
    prn_docs = [d for d in docs if d.get("subject_code") == "PRN232"]
    print(f"Total PRN232 documents returned: {len(prn_docs)}")
    print(f"{'Filename':<35} | {'Displayed Qs':<12} | {'Real Qs (Docx)':<14} | {'Size':<10} | {'Match?'}")
    print("-" * 85)
    for d in prn_docs:
        fn = d.get("filename")
        disp_q = d.get("questions_count")
        fpath = out_dir / fn
        real_q = 0
        if fpath.exists():
            doc = Document(str(fpath))
            real_q = sum(1 for p in doc.paragraphs if p.text.strip().startswith("Câu "))
        is_match = "YES" if disp_q == real_q else "NO (MISMATCH!)"
        print(f"{fn:<35} | {disp_q:<12} | {real_q:<14} | {d.get('size_formatted'):<10} | {is_match}")
