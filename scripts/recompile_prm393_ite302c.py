import sys
import os
import re
import json
import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from docx import Document
from docx.shared import Pt
from bs4 import BeautifulSoup

from backend.app.db.models import Exam, Question, Answer, AnswerStatus, Comment
from backend.app.modules.export.docx_builder import build_exam_docx
from backend.app.modules.crawler.comments import parse_comments_from_html
from backend.app.modules.analysis.voting import tally_votes, Comment as VoteComment


def get_db():
    return sqlite3.connect(str(ROOT_DIR / "data" / "docxstacked.db"))


def print_answers_from_docx(docx_path: Path):
    """
    Read the Word file and print a 10-column answer table (5 rows x 10 cols).
    Identifies answer text by run.font.size == Pt(20) and run.bold == True.
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
            for run in para.runs:
                if run.bold and run.font.size == Pt(20):
                    m_ans = re.match(r"^([A-D](?:\s*,\s*[A-D])*)", run.text.strip())
                    if m_ans:
                        answers[current_q] = m_ans.group(1).strip()
                    elif "?" in run.text:
                        answers[current_q] = "?"
                    break

    # Build 10-column table (5 rows x 10 cols)
    print("\nBẢNG ĐÁP ÁN TRÍCH XUẤT TỪ FILE WORD:")
    print("-" * 65)
    headers = [f"Col {i+1}" for i in range(10)]
    row_headers = ["Câu 01-10", "Câu 11-20", "Câu 21-30", "Câu 31-40", "Câu 41-50"]

    print(f"{'Nhóm':<12} | " + " | ".join(f"{i+1:^4}" for i in range(10)))
    print("-" * 65)

    for row_idx, rname in enumerate(row_headers):
        row_cells = []
        for col_idx in range(10):
            q_num = row_idx * 10 + col_idx + 1
            ans = answers.get(q_num, "-")
            row_cells.append(f"{ans:^4}")
        print(f"{rname:<12} | " + " | ".join(row_cells))
    print("-" * 65)
    return answers


def recompile_exam(exam_id: int, target_q_num: int):
    con = get_db()
    cur = con.cursor()

    # Get exam info
    exam_row = cur.execute("SELECT id, subject_id, title, exam_type, term, raw_folder FROM exams WHERE id = ?", (exam_id,)).fetchone()
    assert exam_row, f"Exam {exam_id} not found"
    
    # Get subject code
    subj_row = cur.execute("SELECT code FROM subjects WHERE id = ?", (exam_row[1],)).fetchone()
    subject_code = subj_row[0] if subj_row else "UNKNOWN"

    print("=" * 70)
    print(f"XỬ LÝ ĐỀ: {subject_code} - {exam_row[2]} (Exam ID: {exam_id})")
    print("=" * 70)

    # Get all questions
    q_rows = cur.execute("SELECT id, [index], file_name, media_url, media_id, local_image_path, cropped_image_path FROM questions WHERE exam_id = ? ORDER BY [index]", (exam_id,)).fetchall()
    print(f"Tổng số câu hỏi: {len(q_rows)}")

    # Record BEFORE answer for target question
    target_q_before = None
    target_q_row = None
    for qr in q_rows:
        if qr[1] == target_q_num:
            target_q_row = qr
            ans_row = cur.execute("SELECT answer_set, status, confidence FROM answers WHERE question_id = ?", (qr[0],)).fetchone()
            if ans_row:
                target_q_before = {
                    "answers": ans_row[0],
                    "status": ans_row[1],
                    "confidence": ans_row[2],
                }
            break

    # Re-parse comments from disk for all questions in this exam
    # Locate raw comments folder
    comments_dir = None
    possible_dirs = [
        ROOT_DIR / f"data/raw/{subject_code}/exam_{exam_id}_{exam_row[4].lower() if exam_row[4] else ''}/comments",
        ROOT_DIR / f"data/raw/{subject_code}/exam_{exam_id}_{exam_row[4] if exam_row[4] else ''}/comments",
        ROOT_DIR / f"data/raw/{subject_code}/exam_{exam_id}/comments",
    ]
    for d in possible_dirs:
        if d.exists():
            comments_dir = d
            break
            
    if not comments_dir:
        # Search by glob
        matches = list((ROOT_DIR / f"data/raw/{subject_code}").glob(f"exam_{exam_id}*/comments"))
        if matches:
            comments_dir = matches[0]

    print(f"Thư mục chứa HTML bình luận: {comments_dir}")
    assert comments_dir and comments_dir.exists(), f"Comments dir not found for exam {exam_id}"

    # For each question, re-parse comments and tally votes
    raw_target_html = None
    answers_map = {}
    questions_list = []

    for qr in q_rows:
        q_id = qr[0]
        q_idx = qr[1]
        
        q_obj = Question(
            id=q_id,
            exam_id=exam_id,
            index=q_idx,
            file_name=qr[2],
            media_url=qr[3],
            media_id=qr[4],
            local_image_path=qr[5],
            cropped_image_path=qr[6],
        )
        questions_list.append(q_obj)

        # Find comment HTML file
        c_files = list(comments_dir.glob(f"q{q_idx:03d}_*.html"))
        if not c_files:
            c_files = list(comments_dir.glob(f"q{q_idx}_*.html"))
            
        if c_files:
            c_path = c_files[0]
            html_content = c_path.read_text(encoding="utf-8")
            if q_idx == target_q_num:
                raw_target_html = html_content
            
            parsed_comms = parse_comments_from_html(html_content, question_id=q_id, html_path=str(c_path))
            
            # Clear old comments for this question and insert updated
            now_iso = datetime.utcnow().isoformat()
            cur.execute("DELETE FROM comments WHERE question_id = ?", (q_id,))
            for pc in parsed_comms:
                cur.execute(
                    """
                    INSERT INTO comments (question_id, comment_id, author_hash, raw_text, upvotes, html_path, is_reply, quoted_comment_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (q_id, pc.comment_id, pc.author_hash, pc.raw_text, pc.upvotes, pc.html_path, pc.is_reply, pc.quoted_comment_id, now_iso)
                )

            # Tally votes with updated weights
            vote_inputs = [
                VoteComment(
                    id=i + 1,
                    comment_id=c.comment_id,
                    author_hash=c.author_hash,
                    raw_text=c.raw_text,
                    upvotes=c.upvotes or 0,
                    is_reply=c.is_reply,
                    quoted_comment_id=c.quoted_comment_id,
                )
                for i, c in enumerate(parsed_comms)
            ]
            tally_res = tally_votes(vote_inputs)
            
            # Save answer to DB
            cur.execute("DELETE FROM answers WHERE question_id = ?", (q_id,))
            cur.execute(
                """
                INSERT INTO answers (question_id, answer_set, status, confidence, valid_comments_count, vote_breakdown, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    q_id,
                    json.dumps(tally_res.answer_set),
                    tally_res.status.value,
                    tally_res.confidence,
                    len(parsed_comms),
                    json.dumps(tally_res.vote_breakdown),
                    now_iso,
                    now_iso,
                )
            )
            
            ans_obj = Answer(
                question_id=q_id,
                answer_set=tally_res.answer_set,
                status=tally_res.status,
                confidence=tally_res.confidence,
                valid_comments_count=len(parsed_comms),
                vote_breakdown=tally_res.vote_breakdown,
            )
            answers_map[q_id] = ans_obj

    con.commit()

    # Get AFTER answer for target question
    target_q_after_row = cur.execute("SELECT answer_set, status, confidence, vote_breakdown FROM answers WHERE question_id = ?", (target_q_row[0],)).fetchone()
    target_q_after = {
        "answers": target_q_after_row[0],
        "status": target_q_after_row[1],
        "confidence": target_q_after_row[2],
        "breakdown": target_q_after_row[3],
    }

    # Print Before / After Table for target question
    print("\n" + "=" * 70)
    print(f"BẢNG SO SÁNH TRƯỚC / SAU CÂU {target_q_num} ({subject_code} - {exam_row[2]})")
    print("=" * 70)
    print(f"| Đề thi               | {subject_code} - {exam_row[2]}")
    print(f"| Câu số               | Câu {target_q_num}")
    print(f"| Đáp án TRƯỚC         | {target_q_before['answers'] if target_q_before else 'N/A'} (Status: {target_q_before['status'] if target_q_before else 'N/A'}, Conf: {target_q_before['confidence'] if target_q_before else 'N/A'})")
    print(f"| Đáp án SAU           | {target_q_after['answers']} (Status: {target_q_after['status']}, Conf: {target_q_after['confidence']})")
    print(f"| Vote Breakdown SAU   | {target_q_after['breakdown']}")
    print("-" * 70)

    # Print raw comments for target question
    print(f"\nCHI TIẾT BÌNH LUẬN THÔ CỦA CÂU {target_q_num}:")
    soup = BeautifulSoup(raw_target_html, "html.parser")
    for i, c in enumerate(soup.select(".message--comment, .message--mediaComment, .js-comment"), 1):
        author_el = c.select_one(".username")
        author = author_el.get_text(strip=True) if author_el else "Unknown"
        vote_el = c.select_one(".user-fuo-vote")
        vote_score = vote_el.get_text(strip=True) if vote_el else "(không có thẻ .user-fuo-vote)"
        rx_bar = c.select_one(".reactionsBar")
        rx_text = rx_bar.get_text(" ", strip=True) if rx_bar else "(trống)"
        body_el = c.select_one(".message-body")
        body = body_el.get_text(" ", strip=True) if body_el else ""
        print(f"  [{i}] Tác giả: {author:<20} | Điểm (.user-fuo-vote): {vote_score:<6} | ReactionsBar: {rx_text:<25} | Nội dung: {body}")
    print("-" * 70)

    # Build Word document
    exam_model = Exam(
        id=exam_row[0],
        subject_id=exam_row[1],
        title=exam_row[2],
        exam_type=exam_row[3],
        term=exam_row[4],
    )
    
    out_dir = ROOT_DIR / "data" / "output" / subject_code
    out_dir.mkdir(parents=True, exist_ok=True)
    
    docx_file = build_exam_docx(
        subject_code=subject_code,
        exam=exam_model,
        questions=questions_list,
        output_dir=out_dir,
        answers_map=answers_map,
        highlight_check_needed=True,
    )
    
    print(f"\nĐã xuất file Word: {docx_file}")

    # Compute SHA-256 and file size
    file_bytes = docx_file.read_bytes()
    sha256_hash = hashlib.sha256(file_bytes).hexdigest()
    size_kb = len(file_bytes) / 1024
    print(f"Kích thước file : {size_kb:.1f} KB ({len(file_bytes)} bytes)")
    print(f"Mã SHA-256      : {sha256_hash}")

    # Print extracted answers from Word
    print_answers_from_docx(docx_file)

    con.close()
    return {
        "exam_title": f"{subject_code} - {exam_row[2]}",
        "docx_path": str(docx_file),
        "sha256": sha256_hash,
        "size_kb": size_kb,
        "before": target_q_before,
        "after": target_q_after,
    }


if __name__ == "__main__":
    print("Bắt đầu biên soạn lại PRM393 - SU26 - FE...")
    res_prm = recompile_exam(39, 31)

    print("\n\nBắt đầu biên soạn lại ITE302c - SU25 - RE...")
    res_ite = recompile_exam(119, 47)
