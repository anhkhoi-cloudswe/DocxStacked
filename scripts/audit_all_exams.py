import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sqlite3
import json
from backend.app.db.models import Comment
from backend.app.modules.analysis.voting import tally_votes

conn = sqlite3.connect('data/docxstacked.db')
c = conn.cursor()

# Get all exams
c.execute('SELECT id, title FROM exams ORDER BY id')
exams = c.fetchall()

print(f"Total exams in DB: {len(exams)}")

total_changed = 0
changed_list = []

for exam_id, exam_title in exams:
    c.execute('SELECT id, "index" FROM questions WHERE exam_id = ? ORDER BY "index"', (exam_id,))
    questions = c.fetchall()
    if not questions:
        continue
    
    exam_changes = []
    for qid, qidx in questions:
        c.execute('SELECT answer_set, status, vote_breakdown FROM answers WHERE question_id = ?', (qid,))
        ans_row = c.fetchone()
        if not ans_row:
            continue
        old_ans_raw, old_status, vb_raw = ans_row
        try:
            old_ans = json.loads(old_ans_raw) if old_ans_raw else []
        except Exception:
            old_ans = [old_ans_raw]

        ai_votes = []
        if vb_raw:
            try:
                vb_data = json.loads(vb_raw)
                if isinstance(vb_data, dict) and "_ai_votes" in vb_data:
                    ai_votes = vb_data["_ai_votes"]
            except Exception:
                pass

        c.execute('SELECT id, comment_id, author_hash, raw_text, upvotes, quoted_comment_id, is_reply FROM comments WHERE question_id = ?', (qid,))
        c_rows = c.fetchall()
        comments = [
            Comment(
                id=r[0],
                comment_id=r[1],
                author_hash=r[2],
                raw_text=r[3],
                upvotes=r[4],
                quoted_comment_id=r[5],
                is_reply=bool(r[6]),
            )
            for r in c_rows
        ]

        # Re-tally with new voting rules
        vr = tally_votes(comments, ai_votes=ai_votes)
        new_ans = vr.answer_set
        new_status = vr.status.value

        if new_ans != old_ans:
            exam_changes.append((qidx, old_ans, new_ans, old_status, new_status))
            total_changed += 1

    if exam_changes:
        changed_list.append((exam_title, exam_changes))

print(f"\n================ AUDIT SUMMARY ================")
print(f"Total questions with changed answers: {total_changed}")
for title, changes in changed_list:
    print(f"\nĐề: {title} ({len(changes)} câu đổi)")
    for qidx, old_a, new_a, old_s, new_s in changes:
        print(f"  - Câu {qidx:02d}: Trước = {old_a} ({old_s}) -> Sau = {new_a} ({new_s})")
