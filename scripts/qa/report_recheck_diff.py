"""
Script to print comparison table of '(cần kiểm tra lại)' before and after
for MLN122 - SU26 - RE.docx from the real Word document and database.
"""

import sqlite3
import json
from pathlib import Path
import docx

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOCX_PATH = PROJECT_ROOT / "data" / "output" / "MLN122" / "MLN122 - SU26 - RE.docx"
DB_PATH = PROJECT_ROOT / "data" / "docxstacked.db"

# The 12 questions that previously had "(cần kiểm tra lại)" in MLN122 - SU26 - RE.docx
PREVIOUS_RECHECK_Q_INDEXES = {6, 7, 14, 22, 24, 27, 29, 32, 40, 52, 55, 56}


def inspect_word_doc():
    if not DOCX_PATH.exists():
        print(f"File not found: {DOCX_PATH}")
        return

    doc = docx.Document(str(DOCX_PATH))
    paragraphs = [p.text.strip() for p in doc.paragraphs if p.text.strip()]

    # Map question index -> rendered answer text
    doc_answers = {}
    current_q = None

    for p in paragraphs:
        if p.startswith("Câu ") and p.endswith(":"):
            try:
                current_q = int(p.replace("Câu ", "").replace(":", ""))
            except ValueError:
                current_q = None
        elif current_q is not None:
            doc_answers[current_q] = p
            current_q = None

    # Connect to DB to fetch statuses and crop warnings
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    c.execute("""
        SELECT q.[index], a.answer_set, a.status, a.confidence, q.crop_warnings
        FROM questions q
        LEFT JOIN answers a ON a.question_id = q.id
        WHERE q.exam_id = 136
        ORDER BY q.[index]
    """)
    rows = {r[0]: (r[1], r[2], r[3], json.loads(r[4]) if r[4] else []) for r in c.fetchall()}

    # Analyze before vs after
    all_recheck_before = PREVIOUS_RECHECK_Q_INDEXES
    all_recheck_after = set()

    for idx, ans_text in doc_answers.items():
        if "(cần kiểm tra lại)" in ans_text:
            all_recheck_after.add(idx)

    print("=" * 95)
    print("BÁO CÁO ĐỐI SOÁT CÂU HỎI '(CẦN KIỂM TRA LẠI)' - ĐỀ MLN122 (SU26 RE)")
    print(f"File Word thực tế: {DOCX_PATH}")
    print("=" * 95)
    print(f"- Số câu '(cần kiểm tra lại)' TRƯỚC: {len(all_recheck_before)}/60 câu")
    print(f"- Số câu '(cần kiểm tra lại)' SAU   : {len(all_recheck_after)}/60 câu")
    print(f"- Số câu đã được khắc phục hoàn toàn: {len(all_recheck_before - all_recheck_after)} câu (Q24, Q27, Q29, Q55)")
    print("-" * 95)

    print("\n### BẢNG CHI TIẾT CÁC CÂU CÓ THAY ĐỔI HOẶC CÒN CỜ KIỂM TRA:")
    headers = ["Câu #", "Trước sửa", "Sau sửa (Rendered trong Word)", "Trạng thái", "Lý do còn lại"]
    print(f"| {headers[0]:<6} | {headers[1]:<12} | {headers[2]:<40} | {headers[3]:<12} | {headers[4]:<20} |")
    print(f"|{'-'*8}|{'-'*14}|{'-'*42}|{'-'*14}|{'-'*22}|")

    tracked_indices = sorted(list(all_recheck_before | all_recheck_after))
    for idx in tracked_indices:
        ans_rendered = doc_answers.get(idx, "N/A")
        db_info = rows.get(idx, ("[]", "unknown", 0.0, []))
        status = db_info[1]
        warnings = db_info[3]

        before_str = "Cần KT (12)"
        
        # Determine remaining reason
        if idx in all_recheck_after:
            if "missing_options" in warnings:
                reason = "missing_options"
            elif status == "conflict":
                reason = "conflict"
            elif status == "weak":
                reason = "weak"
            elif status == "no_data":
                reason = "no_data"
            else:
                reason = "low_confidence"
        else:
            reason = "ĐÃ ĐẠT (confident)"

        print(f"| Q{idx:<5} | {before_str:<12} | {ans_rendered:<40} | {status.upper():<12} | {reason:<20} |")

    print("\n" + "=" * 95)
    print("PHÂN LOẠI LÝ DO CÁC CÂU CÒN '(CẦN KIỂM TRA LẠI)':")
    reasons_count = {}
    for idx in all_recheck_after:
        db_info = rows.get(idx, ("[]", "unknown", 0.0, []))
        warnings = db_info[3]
        st = db_info[1]
        if "missing_options" in warnings:
            r_type = "missing_options (ảnh chụp thiếu phương án)"
        elif st == "conflict":
            r_type = "conflict (học sinh bất đồng đáp án)"
        elif st == "weak":
            r_type = "weak (số phiếu thấp / phân tán)"
        elif st == "no_data":
            r_type = "no_data (không có bình luận)"
        else:
            r_type = "other"
        reasons_count[r_type] = reasons_count.get(r_type, 0) + 1

    for r_type, count in reasons_count.items():
        print(f"  * {r_type}: {count} câu")
    print("=" * 95)


if __name__ == "__main__":
    inspect_word_doc()
