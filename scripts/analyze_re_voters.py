import json
from pathlib import Path
from collections import defaultdict
import re

cache = Path('data/cache/fuexam')
re_dirs = sorted([d for d in cache.glob('media_*') if 're' in list(d.glob('*.webp'))[0].name.lower()])

author_votes = defaultdict(dict)
target_author = 'Phòng Khảo thí FUHCM'

for q_idx, d in enumerate(re_dirs, 1):
    c_file = d / 'comments.json'
    if not c_file.exists():
        continue
    c_data = json.loads(c_file.read_text(encoding='utf-8'))
    for c in c_data.get('comments', []):
        author = c.get('author_name', 'Unknown')
        text = c.get('raw_text', '').strip()
        m = re.search(r'\b([A-E])\b', text, re.IGNORECASE)
        if m:
            author_votes[author][q_idx] = m.group(1).upper()

print('=== THỐNG KÊ NGƯỜI BẦU ĐỀ RE (THREAD 941) ===')
target_dict = author_votes.get(target_author, {})
print(f'Tác giả đối chiếu: "{target_author}" (bầu {len(target_dict)}/50 câu)')

for author, votes in sorted(author_votes.items(), key=lambda x: len(x[1]), reverse=True):
    count = len(votes)
    overlap_qs = [q for q in votes if q in target_dict]
    match_qs = [q for q in overlap_qs if votes[q] == target_dict[q]]
    pct = (len(match_qs) / len(overlap_qs) * 100.0) if overlap_qs else 0.0
    print(f'- Nick: "{author:26s}": bầu {count:2d}/50 câu | Số câu trùng lượt: {len(overlap_qs):2d} | Số câu trùng đáp án: {len(match_qs):2d} ({pct:5.1f}%)')

# Check questions with non-independent consensus
suspect_questions = []
for q in range(1, 51):
    q_voters = {a: author_votes[a][q] for a in author_votes if q in author_votes[a]}
    if len(q_voters) > 1 and target_author in q_voters:
        target_ans = q_voters[target_author]
        # Check if all other voters match target_author 100%
        other_voters = [a for a in q_voters if a != target_author]
        if other_voters and all(q_voters[a] == target_ans for a in other_voters):
            suspect_questions.append((q, target_ans, list(q_voters.keys())))

print(f'\nSố câu có đồng thuận nghi ngờ (tất cả các nick khác trùng 100% với {target_author}): {len(suspect_questions)}/50 ({len(suspect_questions)/50*100:.1f}%)')

