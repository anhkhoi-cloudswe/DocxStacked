import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sqlite3
from backend.app.modules.analysis.voting import tally_votes, Comment as VoteComment
from backend.app.modules.crawler.comments import parse_comments_from_html

con = sqlite3.connect('data/docxstacked.db')
cur = con.cursor()

def inspect_q(exam_id, q_index, raw_html_file=None):
    q = cur.execute('SELECT id, exam_id, [index], file_name, media_url, media_id FROM questions WHERE exam_id = ? AND [index] = ?', (exam_id, q_index)).fetchone()
    print('=' * 60)
    print(f'EXAM {exam_id} - QUESTION {q_index}')
    if not q:
        print('Question not found in DB!')
        return
    q_id = q[0]
    print(f'DB Q_ID: {q_id}, file: {q[3]}, media: {q[4]}')
    
    # 1. Existing comments in DB
    db_comms = cur.execute('SELECT id, comment_id, author_hash, raw_text, upvotes FROM comments WHERE question_id = ?', (q_id,)).fetchall()
    print(f'Existing DB Comments ({len(db_comms)}):')
    for c in db_comms:
        print(f'  • comment_id: {c[1]}, author: {c[2]}, upvotes: {c[4]}, text: {c[3]}')
        
    vote_comms = [VoteComment(id=c[0], comment_id=c[1], author_hash=c[2], raw_text=c[3], upvotes=c[4] or 0) for c in db_comms]
    res_db = tally_votes(vote_comms)
    print(f'DB Vote result: status={res_db.status}, answers={res_db.answer_set}, confidence={res_db.confidence}')
    for opt, v in sorted(res_db.vote_breakdown.items()):
        print(f'    Option {opt}: score={v}')

    # 2. If raw HTML exists on disk, parse with new parser
    if raw_html_file and Path(raw_html_file).exists():
        html_str = Path(raw_html_file).read_text(encoding='utf-8')
        new_parsed = parse_comments_from_html(html_str, question_id=q_id)
        print(f'\nNewly Parsed Comments from disk ({len(new_parsed)}):')
        for c in new_parsed:
            print(f'  • comment_id: {c.comment_id}, author: {c.author_hash}, upvotes: {c.upvotes}, text: {c.raw_text}')
        new_vote_comms = [VoteComment(id=i+1, comment_id=c.comment_id, author_hash=c.author_hash, raw_text=c.raw_text, upvotes=c.upvotes or 0) for i, c in enumerate(new_parsed)]
        res_new = tally_votes(new_vote_comms)
        print(f'New Vote result: status={res_new.status}, answers={res_new.answer_set}, confidence={res_new.confidence}')
        for opt, v in sorted(res_new.vote_breakdown.items()):
            print(f'    Option {opt}: score={v}')

print("Inspecting PRM393 SU26 FE Q31...")
inspect_q(39, 31, "data/raw/PRM393/exam_39_SU26/comments/q031_132856.html")

print("\nInspecting ITE302c SU25 RE Q47...")
inspect_q(119, 47, "data/raw/ITE302C/exam_119_SU25/comments/q047_109917.html")
