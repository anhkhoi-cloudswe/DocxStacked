"""
scripts/verify_docx_answers_report.py
Đọc trực tiếp đáp án từ các đoạn văn trong các file .docx của C1 và C2.
In cùng sha256:
- Với mỗi câu có thay đổi so với lần trước ghi rõ nguồn.
- Liệt kê riêng các câu mà đáp án cộng đồng bị khác đáp án cuối cùng (phải rỗng).
"""

import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from docx import Document

BASE_DIR = Path(__file__).resolve().parent.parent

DOCX_C1 = BASE_DIR / "data" / "output" / "FUE" / "MLN122" / "MLN122 - FUE - FA26 - FE - C1.docx"
DOCX_C2 = BASE_DIR / "data" / "output" / "FUE" / "MLN122" / "MLN122 - FUE - FA26 - FE - C2.docx"


def get_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def extract_docx_answers(docx_path: Path) -> dict[int, str]:
    """Trích xuất map question_index -> answer_text trực tiếp từ các paragraph chứa chữ trong file docx."""
    doc = Document(docx_path)
    non_empty = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    answers: dict[int, str] = {}
    for idx, ans_txt in enumerate(non_empty, start=1):
        answers[idx] = ans_txt
    return answers


def main():
    print("=" * 80)
    print("BÁO CÁO KIỂM TRA ĐÁP ÁN TRÍCH XUẤT TỪ FILE .DOCX")
    print("=" * 80)

    # Dữ liệu đáp án lần chạy trước (bị lỗi ghi đè):
    # C1 câu 14 trước đây là A (ghi đè từ C); C2 câu 53 trước đây là C (ghi đè từ D); C2 câu 23 trước đây là B, C
    previous_answers_c1 = {14: "A"}
    previous_answers_c2 = {23: "B, C", 53: "C"}

    all_community_overridden_questions = []

    for label, docx_p, prev_map, exam_id in [
        ("C1 (Thread 1473)", DOCX_C1, previous_answers_c1, 1473),
        ("C2 (Thread 1474)", DOCX_C2, previous_answers_c2, 1474),
    ]:
        print(f"\n[+] TỆP: {docx_p.name}")
        print(f"    Đường dẫn: {docx_p}")
        sha = get_sha256(docx_p)
        print(f"    SHA256: {sha}")
        
        # Meta info
        meta_p = Path(str(docx_p) + ".meta.json")
        meta = json.loads(meta_p.read_text(encoding="utf-8")) if meta_p.exists() else {}
        print(f"    Review needed questions: {meta.get('review_needed_questions')}")

        answers = extract_docx_answers(docx_p)
        print(f"    Số câu trích xuất thành công từ docx: {len(answers)}/60")

        # So sánh các câu có thay đổi so với lần trước
        print(f"\n    Các câu thay đổi so với lần chạy trước:")
        conn = sqlite3.connect(BASE_DIR / "data" / "docxstacked.db")
        cur = conn.cursor()

        for q_num, prev_val in prev_map.items():
            curr_val = answers.get(q_num, "N/A")
            cur.execute("""
                SELECT a.answer_set, a.status, a.vote_breakdown
                FROM questions q
                JOIN answers a ON q.id = a.question_id
                WHERE q.exam_id = ? AND q.[index] = ?
            """, (exam_id, q_num))
            row = cur.fetchone()
            vb = json.loads(row[2]) if row and row[2] else {}
            source_info = vb.get("_source", "N/A")
            print(f"      - Câu {q_num}:")
            print(f"          + Lần trước: {prev_val}")
            print(f"          + Lần này (trong docx): {curr_val}")
            print(f"          + Trạng thái: {row[1] if row else 'N/A'}")
            print(f"          + Nguồn: {source_info} (Chi tiết: {vb})")

        # Kiểm tra điều kiện: Liệt kê riêng các câu mà đáp án cộng đồng bị khác đáp án cuối cùng
        cur.execute("""
            SELECT q.[index], a.answer_set, a.status, a.vote_breakdown
            FROM questions q
            JOIN answers a ON q.id = a.question_id
            WHERE q.exam_id = ?
        """, (exam_id,))
        for q_idx, ans_set_str, st, vb_str in cur.fetchall():
            vb = json.loads(vb_str) if vb_str else {}
            # Nếu có bình luận cộng đồng
            if vb.get("_source") == "comments":
                final_ans = json.loads(ans_set_str)
                # Tìm option cộng đồng thắng
                comm_options = {k: v for k, v in vb.items() if not k.startswith("_")}
                if comm_options:
                    top_comm_opt = max(comm_options.items(), key=lambda x: x[1])[0]
                    # Nếu đáp án cuối cùng không chứa đáp án cộng đồng hàng đầu
                    if top_comm_opt not in final_ans:
                        all_community_overridden_questions.append((exam_id, q_idx, top_comm_opt, final_ans))

    print("\n" + "=" * 80)
    print("LIỆT KÊ RIÊNG CÁC CÂU MÀ ĐÁP ÁN CỘNG ĐỒNG BỊ KHÁC ĐÁP ÁN CUỐI CÙNG:")
    if not all_community_overridden_questions:
        print("  [] (RỖNG - Không có câu nào đáp án cộng đồng bị ghi đè hoặc khác đáp án cuối cùng)")
    else:
        for exam_id, q_idx, comm_ans, final_ans in all_community_overridden_questions:
            print(f"  - Đề {exam_id} câu {q_idx}: Cộng đồng = {comm_ans}, Cuối cùng = {final_ans}")
    print("=" * 80)


if __name__ == "__main__":
    main()
