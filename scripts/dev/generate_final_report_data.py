import sys
import hashlib
from pathlib import Path
repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from docx import Document

from backend.app.db.models import Exam, Question, Comment, Answer

def get_docx_answers(docx_path: Path):
    doc = Document(str(docx_path))
    answers = []
    cur_q = None
    for p in doc.paragraphs:
        t = p.text.strip()
        if t.startswith("Câu ") and ":" in t:
            cur_q = t.split(":")[0].strip()
        elif cur_q and (t.startswith("A") or t.startswith("B") or t.startswith("C") or t.startswith("D") or t.startswith("?")):
            answers.append((cur_q, t))
            cur_q = None
    return answers

def main():
    db_path = repo_root / "data" / "docxstacked.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Session = sessionmaker(bind=engine)
    session = Session()

    print("=" * 80)
    print("MỤC 1: TRÍCH XUẤT ĐÁP ÁN BẰNG PYTHON-DOCX & SHA256/FILE SIZE")
    print("=" * 80)

    exams_to_extract = [
        (194, "data/output/PRN232/PRN232 - SU25 - Final Exam.docx"),
        (195, "data/output/PRN232/PRN232 - SU26 - B5 - FE.docx"),
        (192, "data/output/PRN232/PRN232 - SU26 - FE.docx"),
    ]

    for eid, rel_path in exams_to_extract:
        p = repo_root / rel_path
        if not p.exists():
            print(f"File not found: {p}")
            continue

        raw_bytes = p.read_bytes()
        sha256 = hashlib.sha256(raw_bytes).hexdigest()
        size = len(raw_bytes)
        print(f"\n[EXAM ID {eid}] File: {p.name}")
        print(f"  Path: {p}")
        print(f"  Size: {size} bytes")
        print(f"  SHA256: {sha256}")

        ans_list = get_docx_answers(p)
        print(f"  Total extracted questions: {len(ans_list)}")
        print("  Answers table:")
        for idx in range(0, len(ans_list), 10):
            batch = ans_list[idx:idx+10]
            line_str = " | ".join(f"{q.replace('Câu ', 'Q')}: {a}" for q, a in batch)
            print(f"    {line_str}")

    print("\n" + "=" * 80)
    print("MỤC 2: BẢNG BÌNH LUẬN THÔ CHO FINAL EXAM (EXAM 194) Q3, Q7, Q18")
    print("=" * 80)

    for q_idx in [3, 7, 18]:
        q = session.query(Question).filter(Question.exam_id == 194, Question.index == q_idx).first()
        ans = session.query(Answer).filter(Answer.question_id == q.id).first() if q else None
        print(f"\n--- Câu {q_idx} (Exam 194: PRN232 - SU25 - Final Exam) ---")
        ans_str = ','.join(ans.answer_set) if (ans and ans.answer_set) else 'N/A'
        print(f"  Đáp án chốt: {ans_str} (Trạng thái: {ans.status if ans else 'N/A'}, Tự tin: {ans.confidence if ans else 'N/A'})")

        comments = session.query(Comment).filter(Comment.question_id == q.id).all() if q else []
        print(f"  Tổng số bình luận: {len(comments)}")
        print(f"  {'Tác giả (Hash)':<20} | {'Điểm upvote':<11} | {'Bình luận thô'}")
        print("  " + "-" * 75)
        for c in comments:
            raw = c.raw_text.replace('\n', ' ')
            print(f"  {c.author_hash[:18]:<20} | {c.upvotes:<11} | {raw}")

    print("\n" + "=" * 80)
    print("MỤC 3: SỐ LẦN GỌI AI THỰC TẾ CỦA B5 (EXAM 195) THEO TỪNG CÂU")
    print("=" * 80)

    ai_questions = []
    non_ai_questions = []

    for q_idx in range(1, 51):
        q = session.query(Question).filter(Question.exam_id == 195, Question.index == q_idx).first()
        if not q:
            continue
        ans = session.query(Answer).filter(Answer.question_id == q.id).first()
        breakdown = ans.vote_breakdown if ans else {}
        ai_votes = breakdown.get("_ai_votes", []) if isinstance(breakdown, dict) else []
        if ai_votes:
            v_info = ", ".join(f"{','.join(v.get('answers', []))} (provider={v.get('provider')}, conf={v.get('confidence')})" for v in ai_votes)
            ai_questions.append((q_idx, len(ai_votes), v_info))
        else:
            non_ai_questions.append(q_idx)

    print(f"Tổng số câu có phiếu AI: {len(ai_questions)}/50")
    print(f"Tổng số câu KHÔNG có phiếu AI: {len(non_ai_questions)}/50")
    print("\nChi tiết các câu có phiếu AI:")
    for q_idx, cnt, v_info in ai_questions:
        print(f"  Q{q_idx:02d}: {cnt} lần gọi AI -> Phiếu: {v_info}")

    print("\nCác câu không gọi AI:")
    print("  " + ", ".join(f"Q{q:02d}" for q in non_ai_questions))

if __name__ == "__main__":
    main()
