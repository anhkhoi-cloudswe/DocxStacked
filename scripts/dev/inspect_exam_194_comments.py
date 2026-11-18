import sqlite3
import json

def inspect_exam_194_comments():
    conn = sqlite3.connect("data/docxstacked.db")
    cursor = conn.cursor()
    
    # Get questions for exam 194
    questions = cursor.execute("SELECT id, `index` FROM questions WHERE exam_id=194 ORDER BY `index`").fetchall()
    q_map = {q[1]: q[0] for q in questions}
    
    for q_idx in [2, 6, 8]:
        q_id = q_map.get(q_idx)
        print(f"\n==================== Q{q_idx} (question_id={q_id}) ====================")
        # Check current answer in DB
        ans = cursor.execute("SELECT answer_set, confidence, status, vote_breakdown FROM answers WHERE question_id=?", (q_id,)).fetchone()
        if ans:
            print(f"Current DB Answer: {ans[0]} (conf={ans[1]}, status={ans[2]})")
            print(f"Vote breakdown: {ans[3]}")
        else:
            print("No answer in DB!")

        # Check raw comments
        comments = cursor.execute("SELECT id, author_hash, raw_text, upvotes, posted_at FROM comments WHERE question_id=? ORDER BY id", (q_id,)).fetchall()
        print(f"Total comments: {len(comments)}")
        for c in comments[:5]:
            print(f"  Comment ID: {c[0]} | Author: {c[1]} | Score/Upvotes: {c[3]}")
            print(f"  Text: {repr(c[2])}")

if __name__ == "__main__":
    inspect_exam_194_comments()
