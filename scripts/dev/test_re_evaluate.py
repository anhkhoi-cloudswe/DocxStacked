import sys
import json
import sqlite3
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))

from backend.app.modules.analysis.voting import tally_votes
from backend.app.db.models import Comment

def re_evaluate_exam_answers(exam_id: int):
    conn = sqlite3.connect("data/docxstacked.db")
    cursor = conn.cursor()
    
    questions = cursor.execute("SELECT id, [index] FROM questions WHERE exam_id=? ORDER BY [index]", (exam_id,)).fetchall()
    
    results = []
    changes = []
    
    for q_id, q_idx in questions:
        # Existing answer
        old_ans_row = cursor.execute("SELECT answer_set, confidence, status, vote_breakdown FROM answers WHERE question_id=?", (q_id,)).fetchone()
        old_ans_set = json.loads(old_ans_row[0]) if old_ans_row and old_ans_row[0] else []
        old_status = old_ans_row[2] if old_ans_row else "NONE"
        old_breakdown = old_ans_row[3] if old_ans_row else "{}"
        
        # Comments
        comm_rows = cursor.execute("SELECT id, comment_id, author_hash, raw_text, upvotes, quoted_comment_id FROM comments WHERE question_id=? ORDER BY id", (q_id,)).fetchall()
        comments = [
            Comment(
                id=r[0],
                question_id=q_id,
                comment_id=r[1],
                author_hash=r[2],
                raw_text=r[3],
                upvotes=r[4],
                quoted_comment_id=r[5],
            )
            for r in comm_rows
        ]
        
        # New tally
        new_res = tally_votes(comments=comments, max_option_letter="D")
        results.append((q_idx, old_ans_set, new_res.answer_set, old_status, new_res.status.value, new_res.vote_breakdown))
        
        if old_ans_set != new_res.answer_set or old_status != new_res.status.value:
            changes.append((q_idx, old_ans_set, new_res.answer_set, old_status, new_res.status.value, old_breakdown, new_res.vote_breakdown))
            
    print(f"\n=================== EXAM {exam_id} ===================")
    print(f"Total questions: {len(questions)}")
    print(f"Questions changed: {len(changes)}")
    print("\nChanged questions:")
    for c in changes:
        print(f"Q{c[0]:02d}: Old {c[1]} ({c[3]}) -> New {c[2]} ({c[4]})")
        print(f"   Old breakdown: {c[5]}")
        print(f"   New breakdown: {c[6]}")

    return results

if __name__ == "__main__":
    print("Testing re-evaluation for Exam 194 (SU25 Final Exam):")
    re_evaluate_exam_answers(194)
    print("\nTesting re-evaluation for Exam 195 (SU26 B5 FE):")
    re_evaluate_exam_answers(195)
