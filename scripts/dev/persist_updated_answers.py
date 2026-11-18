import sys
import json
import sqlite3
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))

from backend.app.modules.analysis.voting import tally_votes
from backend.app.db.models import Comment, AnswerStatus

def update_db_answers(exam_id: int):
    conn = sqlite3.connect("data/docxstacked.db")
    cursor = conn.cursor()
    
    questions = cursor.execute("SELECT id, [index] FROM questions WHERE exam_id=? ORDER BY [index]", (exam_id,)).fetchall()
    
    print(f"Updating DB answers for exam {exam_id} ({len(questions)} questions)...")
    for q_id, q_idx in questions:
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
        
        # Check if existing answer had _options or _ai_votes
        old_ans = cursor.execute("SELECT vote_breakdown FROM answers WHERE question_id=?", (q_id,)).fetchone()
        ai_votes = None
        if old_ans and old_ans[0]:
            try:
                vb = json.loads(old_ans[0])
                if "_ai_votes" in vb:
                    ai_votes = vb["_ai_votes"]
            except Exception:
                pass
                
        new_res = tally_votes(comments=comments, max_option_letter="D", ai_votes=ai_votes)
        
        vb_dict = dict(new_res.vote_breakdown)
        if ai_votes:
            vb_dict["_ai_votes"] = ai_votes
            
        cursor.execute(
            """
            UPDATE answers
            SET answer_set=?, confidence=?, status=?, vote_breakdown=?, updated_at=datetime('now')
            WHERE question_id=?
            """,
            (
                json.dumps(new_res.answer_set),
                new_res.confidence,
                new_res.status.value.upper(),
                json.dumps(vb_dict),
                q_id,
            )
        )
    conn.commit()
    print(f"Done updating exam {exam_id} answers.")

if __name__ == "__main__":
    update_db_answers(194)
    update_db_answers(195)
