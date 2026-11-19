import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

# Ensure root in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from docx import Document
from docx.shared import Pt
from backend.app.db.models import Exam, Question, Answer, AnswerStatus
from backend.app.modules.export.docx_builder import build_exam_docx
from backend.app.modules.analysis.voting import tally_votes, Comment as VoteComment

def get_db():
    return sqlite3.connect(str(BASE_DIR / "data" / "docxstacked.db"))

def extract_answers_and_flags_from_docx(docx_path: Path):
    """
    Extract answers and flags from the docx file.
    Returns: dict {q_num: (answer_str, is_flagged)}
    """
    doc = Document(str(docx_path))
    answers = {}
    current_q = None

    for para in doc.paragraphs:
        text = para.text.strip()
        m = re.match(r"^Câu\s+(\d+)\s*:", text)
        if m:
            current_q = int(m.group(1))
            continue

        if current_q is not None:
            # Check runs in paragraph
            ans_found = None
            is_flagged = False
            for run in para.runs:
                if run.bold and run.font.size == Pt(20):
                    ans_found = run.text.strip()
                if "(cần kiểm tra lại)" in run.text:
                    is_flagged = True
            
            if ans_found is not None:
                answers[current_q] = (ans_found, is_flagged)
                current_q = None

    return answers

def print_10col_table(title: str, answers: dict, total_q: int):
    print(f"\n=======================================================")
    print(f" BẢNG ĐÁP ÁN TRÍCH XUẤT TỪ FILE WORD (KÈM CỜ): {title}")
    print(f"=======================================================")
    print(f"{'Nhóm':<12} | " + " | ".join(f"{i+1:^5}" for i in range(10)))
    print("-" * 75)

    num_rows = (total_q + 9) // 10
    flagged_count = 0

    for r_idx in range(num_rows):
        start_q = r_idx * 10 + 1
        end_q = min((r_idx + 1) * 10, total_q)
        rname = f"Câu {start_q:02d}-{end_q:02d}"
        
        cells = []
        for c_idx in range(10):
            q_num = r_idx * 10 + c_idx + 1
            if q_num <= total_q:
                ans_tuple = answers.get(q_num, ("-", False))
                ans_str, flagged = ans_tuple
                if flagged:
                    flagged_count += 1
                    cell_val = f"{ans_str}*"
                else:
                    cell_val = f"{ans_str}"
                cells.append(f"{cell_val:^5}")
            else:
                cells.append("     ")
        print(f"{rname:<12} | " + " | ".join(cells))

    print("-" * 75)
    print(f"Ghi chú: Ký hiệu '*' biểu thị câu có gắn nhãn '(cần kiểm tra lại)'.")
    print(f"Tổng số câu có cờ: {flagged_count}/{total_q}")

def print_full_answers_table(title: str, answers: dict, total_q: int):
    print(f"\n=======================================================")
    print(f" BẢNG ĐÁP ÁN NGUYÊN CHUỖI TRÍCH XUẤT TỪ FILE WORD: {title}")
    print(f"=======================================================")
    print(f"{'Câu':<6} | {'Đáp án nguyên chuỗi trong Word':<45} | {'Cần ktra':<10}")
    print("-" * 68)
    for q in range(1, total_q + 1):
        ans_str, flagged = answers.get(q, ("-", False))
        flag_str = "CÓ CỜ (*)" if flagged else "Không"
        print(f"Câu {q:02d} | {ans_str:<45} | {flag_str:<10}")
    print("-" * 68)

def count_images_in_docx(docx_path: Path) -> int:
    doc = Document(str(docx_path))
    count = 0
    for rel in doc.part.rels.values():
        if "image" in rel.target_ref:
            count += 1
    return count

def sha256_and_size(path: Path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    size_bytes = os.path.getsize(path)
    return h.hexdigest(), size_bytes

def recompile_ite302c():
    con = get_db()
    cur = con.cursor()
    exam_id = 119
    
    exam_row = cur.execute("SELECT id, subject_id, title, exam_type, term, raw_folder FROM exams WHERE id = ?", (exam_id,)).fetchone()
    subj_row = cur.execute("SELECT code, name FROM subjects WHERE id = ?", (exam_row[1],)).fetchone()
    subject_code = subj_row[0]
    
    # 1. Update answers for Exam 119 with new voting rules
    q_rows = cur.execute("""
        SELECT id, [index], file_name, media_url, media_id, local_image_path, cropped_image_path, crop_warnings
        FROM questions
        WHERE exam_id = ?
        ORDER BY [index]
    """, (exam_id,)).fetchall()

    for qr in q_rows:
        qid = qr[0]
        qidx = qr[1]
        
        # Get comments
        cmts = cur.execute("""
            SELECT id, comment_id, author_hash, raw_text, upvotes, is_reply, quoted_comment_id
            FROM comments
            WHERE question_id = ?
            ORDER BY id ASC
        """, (qid,)).fetchall()
        
        vote_inputs = [
            VoteComment(
                id=c[0],
                comment_id=c[1],
                author_hash=c[2],
                raw_text=c[3],
                upvotes=c[4] or 0,
                is_reply=bool(c[5]),
                quoted_comment_id=c[6],
            )
            for c in cmts
        ]
        
        # Check if previous answer had AI votes
        prev_ans = cur.execute("SELECT vote_breakdown FROM answers WHERE question_id = ?", (qid,)).fetchone()
        ai_votes = None
        if prev_ans and prev_ans[0]:
            try:
                bd = json.loads(prev_ans[0])
                if "_ai_votes" in bd:
                    ai_votes = bd["_ai_votes"]
            except:
                pass

        t_res = tally_votes(vote_inputs, ai_votes=ai_votes)
        
        bd_dict = dict(t_res.vote_breakdown)
        if ai_votes:
            bd_dict["_ai_votes"] = ai_votes

        cur.execute("""
            UPDATE answers
            SET answer_set = ?, confidence = ?, status = ?, valid_comments_count = ?, vote_breakdown = ?, updated_at = CURRENT_TIMESTAMP
            WHERE question_id = ?
        """, (json.dumps(t_res.answer_set), t_res.confidence, t_res.status.value, t_res.voters_count, json.dumps(bd_dict), qid))

    con.commit()

    # Re-fetch objects for docx_builder
    exam = Exam(
        id=exam_row[0],
        subject_id=exam_row[1],
        title=exam_row[2],
        exam_type=exam_row[3],
        term=exam_row[4],
        raw_folder=exam_row[5],
    )
    
    questions = []
    answers_map = {}
    for qr in q_rows:
        q_obj = Question(
            id=qr[0],
            exam_id=exam_id,
            index=qr[1],
            file_name=qr[2],
            media_url=qr[3],
            media_id=qr[4],
            local_image_path=qr[5],
            cropped_image_path=qr[6],
            crop_warnings=qr[7],
        )
        questions.append(q_obj)
        
        a_row = cur.execute("SELECT id, answer_set, status, confidence, vote_breakdown FROM answers WHERE question_id = ?", (qr[0],)).fetchone()
        if a_row:
            ans_obj = Answer(
                id=a_row[0],
                question_id=qr[0],
                answer_set=json.loads(a_row[1]) if a_row[1] else ["?"],
                status=AnswerStatus(a_row[2]) if a_row[2] else AnswerStatus.NO_DATA,
                confidence=a_row[3] or 0.0,
                vote_breakdown=json.loads(a_row[4]) if a_row[4] else {},
            )
            answers_map[qr[0]] = ans_obj

    con.close()

    out_dir = BASE_DIR / "data" / "output" / subject_code
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nBuilding Word document for {exam.title}...")
    out_docx = build_exam_docx(
        subject_code=subject_code,
        exam=exam,
        questions=questions,
        output_dir=out_dir,
        answers_map=answers_map,
    )
    print(f"Successfully generated: {out_docx}")

    # Inspect docx
    img_count = count_images_in_docx(out_docx)
    sha, size = sha256_and_size(out_docx)
    print(f"Số lượng ảnh trong file docx: {img_count} (Kỳ vọng: {len(questions)})")
    print(f"Kích thước file: {size:,} bytes ({size / (1024*1024):.2f} MB)")
    print(f"SHA-256: {sha}")

    extracted_ans = extract_answers_and_flags_from_docx(out_docx)
    print_10col_table("ITE302c - SU25 - RE", extracted_ans, len(questions))

    return out_docx, sha, size, img_count, extracted_ans

def recompile_prm393():
    con = get_db()
    cur = con.cursor()
    exam_id = 39

    exam_row = cur.execute("SELECT id, subject_id, title, exam_type, term, raw_folder FROM exams WHERE id = ?", (exam_id,)).fetchone()
    subj_row = cur.execute("SELECT code, name FROM subjects WHERE id = ?", (exam_row[1],)).fetchone()
    subject_code = subj_row[0]

    q_rows = cur.execute("""
        SELECT id, [index], file_name, media_url, media_id, local_image_path, cropped_image_path, crop_warnings
        FROM questions
        WHERE exam_id = ?
        ORDER BY [index]
    """, (exam_id,)).fetchall()

    exam = Exam(
        id=exam_row[0],
        subject_id=exam_row[1],
        title=exam_row[2],
        exam_type=exam_row[3],
        term=exam_row[4],
        raw_folder=exam_row[5],
    )

    questions = []
    answers_map = {}
    for qr in q_rows:
        q_obj = Question(
            id=qr[0],
            exam_id=exam_id,
            index=qr[1],
            file_name=qr[2],
            media_url=qr[3],
            media_id=qr[4],
            local_image_path=qr[5],
            cropped_image_path=qr[6],
            crop_warnings=qr[7],
        )
        questions.append(q_obj)

        a_row = cur.execute("SELECT id, answer_set, status, confidence, vote_breakdown FROM answers WHERE question_id = ?", (qr[0],)).fetchone()
        if a_row:
            ans_obj = Answer(
                id=a_row[0],
                question_id=qr[0],
                answer_set=json.loads(a_row[1]) if a_row[1] else ["?"],
                status=AnswerStatus(a_row[2]) if a_row[2] else AnswerStatus.NO_DATA,
                confidence=a_row[3] or 0.0,
                vote_breakdown=json.loads(a_row[4]) if a_row[4] else {},
            )
            answers_map[qr[0]] = ans_obj

    con.close()

    out_dir = BASE_DIR / "data" / "output" / subject_code
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nBuilding Word document for {exam.title}...")
    out_docx = build_exam_docx(
        subject_code=subject_code,
        exam=exam,
        questions=questions,
        output_dir=out_dir,
        answers_map=answers_map,
    )
    print(f"Successfully generated: {out_docx}")

    img_count = count_images_in_docx(out_docx)
    sha, size = sha256_and_size(out_docx)
    print(f"Số lượng ảnh trong file docx: {img_count} (Kỳ vọng: {len(questions)})")
    print(f"Kích thước file: {size:,} bytes ({size / (1024*1024):.2f} MB)")
    print(f"SHA-256: {sha}")

    extracted_ans = extract_answers_and_flags_from_docx(out_docx)
    print_10col_table("PRM393 - SU26 - FE", extracted_ans, len(questions))
    print_full_answers_table("PRM393 - SU26 - FE", extracted_ans, len(questions))

    return out_docx, sha, size, img_count, extracted_ans

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode in ("ite302c", "all"):
        recompile_ite302c()
    if mode in ("prm393", "all"):
        recompile_prm393()
