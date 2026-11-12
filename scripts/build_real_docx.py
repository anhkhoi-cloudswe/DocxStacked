import os
import sys
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

import json
import sqlite3
from backend.app.db.models import Exam, Question, Answer
from backend.app.modules.export.docx_builder import build_exam_docx

def main():
    conn = sqlite3.connect('data/docxstacked.db')
    c = conn.cursor()
    c.execute("SELECT id, title, term, exam_type FROM exams WHERE title LIKE '%SU26%FE%' LIMIT 1")
    exam_row = c.fetchone()
    print('Exam row:', exam_row)
    exam_id = exam_row[0]

    c.execute("SELECT id, [index], file_name, local_image_path FROM questions WHERE exam_id = ? ORDER BY [index]", (exam_id,))
    q_rows = c.fetchall()
    print('Questions count:', len(q_rows))

    questions = []
    for qid, qidx, fname, img_path in q_rows:
        q = Question(id=qid, exam_id=exam_id, index=qidx, file_name=fname, local_image_path=img_path)
        c.execute("SELECT answer_set, status, vote_breakdown FROM answers WHERE question_id = ?", (qid,))
        a_row = c.fetchone()
        if a_row:
            ans = Answer(
                answer_set=json.loads(a_row[0]),
                status=a_row[1],
                vote_breakdown=json.loads(a_row[2]) if a_row[2] else {}
            )
            q.answer = ans
        questions.append(q)

    exam = Exam(id=exam_id, title=exam_row[1], term=exam_row[2], exam_type=exam_row[3])
    out_path = build_exam_docx('CSD202', exam, questions, output_dir=Path('data/output/CSD202'))
    print('Saved docx to:', out_path)

if __name__ == '__main__':
    main()
