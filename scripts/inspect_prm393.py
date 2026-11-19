import sqlite3
import json

conn = sqlite3.connect("data/docxstacked.db")
c = conn.cursor()

c.execute("""
    SELECT q.id, q."index", q.file_name, q.local_image_path, a.answer_set, a.confidence, a.status, a.valid_comments_count, a.vote_breakdown, a.explanation, q.crop_warnings
    FROM questions q
    LEFT JOIN answers a ON a.question_id = q.id
    WHERE q.exam_id = 39
    ORDER BY q."index" ASC
""")
rows = c.fetchall()
print(f"Total questions for exam 39: {len(rows)}")

c.execute("SELECT question_id, count(*), count(distinct author_hash) FROM comments WHERE question_id IN (SELECT id FROM questions WHERE exam_id = 39) GROUP BY question_id")
comments_counts = {r[0]: (r[1], r[2]) for r in c.fetchall()}

print(f"{'Câu':<5} | {'Số cmt':<7} | {'Người độc lập':<14} | {'Trạng thái':<12} | {'Có AI':<7} | {'Có cờ':<7}")
print("-" * 65)

flagged_count = 0
for r in rows:
    qid, idx, fn, img_path, ans_set, conf, status, valid_cmts, vote_bd, explanation, crop_warn = r
    cmt_count, indep_count = comments_counts.get(qid, (0, 0))
    
    # check if AI vote is recorded
    has_ai = False
    if explanation and ("AI Analysis" in explanation or "ai_" in explanation):
        has_ai = True
    elif vote_bd and ("ai_" in vote_bd or "provider" in vote_bd):
        has_ai = True
    
    raw_warnings = crop_warn
    if isinstance(raw_warnings, str):
        try:
            raw_warnings = json.loads(raw_warnings)
        except Exception:
            raw_warnings = [raw_warnings]
    if raw_warnings == "":
        raw_warnings = []

    ans_text = ",".join(json.loads(ans_set)) if ans_set else "?"
    is_flagged = (
        status in ('conflict', 'weak', 'no_data')
        or ans_text.startswith('?')
        or bool(raw_warnings)
    )
    if is_flagged:
        flagged_count += 1
    
    print(f"{idx:<5} | {cmt_count:<7} | {indep_count:<14} | {str(status):<12} | {str(has_ai):<7} | {str(is_flagged):<7}")

print("-" * 65)
print(f"Total flagged questions: {flagged_count}/{len(rows)}")
