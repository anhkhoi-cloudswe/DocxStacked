import json
import sqlite3
from pathlib import Path

conn = sqlite3.connect("data/docxstacked.db")
c = conn.cursor()

exam_id = 119
c.execute("SELECT id, term, exam_type, title, question_count FROM exams WHERE id=?", (exam_id,))
print("Exam 119:", c.fetchone())

c.execute("SELECT count(*) FROM questions WHERE exam_id=?", (exam_id,))
print("Questions count:", c.fetchone()[0])

# Inspect Q47 specifically
c.execute("""
    SELECT q.id, q."index", q.file_name, a.answer_set, a.confidence, a.status, a.vote_breakdown
    FROM questions q
    LEFT JOIN answers a ON a.question_id = q.id
    WHERE q.exam_id = ? AND q."index" = 47
""", (exam_id,))
q47 = c.fetchone()
print("Q47 row:", q47)

c.execute("""
    SELECT id, comment_id, author_hash, raw_text, upvotes
    FROM comments
    WHERE question_id = ?
    ORDER BY id ASC
""", (q47[0],))
cmts = c.fetchall()
print(f"Q47 total comments: {len(cmts)}")
for cmt in cmts:
    print(f" - {cmt[2]}: {repr(cmt[3][:50])} (upvotes={cmt[4]})")
