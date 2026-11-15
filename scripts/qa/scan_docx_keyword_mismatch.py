import docx
import re
import sys
from pathlib import Path

def scan_docx(docx_path: str):
    p = Path(docx_path)
    if not p.exists():
        print(f"File not found: {docx_path}")
        sys.exit(1)

    doc = docx.Document(str(p))
    current_q = None
    mismatches = []
    
    for para in doc.paragraphs:
        t = para.text.strip()
        m = re.match(r"^Câu\s+(\d+):?", t)
        if m:
            current_q = int(m.group(1))
        elif current_q and re.match(r"^[A-D]\.\s+", t):
            kw = re.sub(r"^[A-D]\.\s+", "", t)
            # Remove any trailing warnings like (cần kiểm tra lại)
            kw_clean = re.sub(r"\(.*?\)", "", kw).strip()
            has_vi = bool(re.search(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", kw_clean.lower()))
            if not has_vi and any(c.isalpha() for c in kw_clean):
                mismatches.append((current_q, t, kw_clean, "Từ khóa tiếng Anh không khớp với đề bài tiếng Việt"))

    print("==================================================")
    print(f"BÁO CÁO QUÉT TỪ KHÓA FILE WORD: {p.name}")
    print(f"Tổng số từ khóa bị phát hiện không khớp ngôn ngữ: {len(mismatches)}")
    print("==================================================")
    for q_num, full_text, kw_clean, reason in mismatches:
        print(f"Câu {q_num}:")
        print(f"  Văn bản trong Word: '{full_text}'")
        print(f"  Từ khóa trích xuất: '{kw_clean}'")
        print(f"  Cảnh báo: {reason}")
    print("==================================================")

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "data/output/MLN122/MLN122 - SU26 - RE.docx"
    scan_docx(path)
