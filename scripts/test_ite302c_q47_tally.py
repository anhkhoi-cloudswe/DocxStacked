import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app.modules.analysis.voting import tally_votes, Comment as VoteComment
from backend.app.modules.analysis.parser import parse_comment_text

conn = sqlite3.connect("data/docxstacked.db")
c = conn.cursor()

# Get comments for Q47 of Exam 119
c.execute("""
    SELECT c.id, c.comment_id, c.author_hash, c.raw_text, c.upvotes, c.is_reply, c.quoted_comment_id
    FROM comments c
    JOIN questions q ON q.id = c.question_id
    WHERE q.exam_id = 119 AND q."index" = 47
    ORDER BY c.id ASC
""")
rows = c.fetchall()
print(f"Total comments for Q47: {len(rows)}")

vote_inputs = []
for r in rows:
    cid, comment_id, author_hash, raw_text, upvotes, is_reply, quoted_id = r
    parsed = parse_comment_text(raw_text or "")
    print(f"Author {author_hash[:8]} | text: {raw_text!r:<30} | parsed: {parsed.answers} (ambig={parsed.is_ambiguous}) | upvotes: {upvotes}")
    vote_inputs.append(
        VoteComment(
            id=cid,
            comment_id=comment_id,
            author_hash=author_hash,
            raw_text=raw_text,
            upvotes=upvotes or 0,
            is_reply=bool(is_reply),
            quoted_comment_id=quoted_id,
        )
    )

res = tally_votes(vote_inputs)
print("\n--- KẾT QUẢ TÍNH PHIẾU Q47 ---")
print(f"Answer set: {res.answer_set}")
print(f"Status: {res.status}")
print(f"Confidence: {res.confidence}")
print(f"Total weight: {res.total_weight}")
print(f"Vote breakdown: {res.vote_breakdown}")
print(f"Voters count: {res.voters_count}")

# Count independent voters per option
voters_by_opt = {}
for c_contrib in res.contributions:
    for ans in c_contrib.answers:
        voters_by_opt.setdefault(ans, set()).add(c_contrib.author_hash)

for opt, vset in sorted(voters_by_opt.items()):
    print(f"Option {opt}: {len(vset)} người độc lập -> {list(vset)}")
