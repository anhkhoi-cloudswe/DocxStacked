import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.modules.analysis.voting import tally_votes
from backend.app.db.models import Comment

c_data = json.loads(Path("data/cache/fuexam/media_34522/comments.json").read_text(encoding="utf-8"))
raw = c_data["comments"]
print("Total comments in JSON:", len(raw))
q_comments = []
for i, c in enumerate(raw, 1):
    print(f"  Comment {i}: {c['author_name']} ({c['author_hash']}) -> '{c['raw_text']}'")
    q_comments.append(Comment(
        id=i,
        question_id=1,
        comment_id=str(c.get("comment_id", i)),
        author_hash=c.get("author_hash"),
        raw_text=c.get("raw_text", ""),
        upvotes=0,
    ))
res = tally_votes(q_comments)
print("tally_votes voters_count:", res.voters_count)
print("tally_votes answer_set:", res.answer_set)
print("tally_votes contributions:", len(res.contributions))
for vc in res.contributions:
    print("  vc:", vc.author_hash, vc.answers, vc.weight)
