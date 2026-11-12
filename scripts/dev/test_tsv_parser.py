from pathlib import Path
from backend.app.modules.analysis.parser import parse_comment_text

tsv_path = Path("data/exports/comments_CSD202.tsv")
lines = tsv_path.read_text(encoding="utf-8").strip().split("\n")
header = lines[0].split("\t")

parsed_results = []
unparsed_count = 0

print(f"Testing {len(lines) - 1} real comments from TSV:\n")
for i, line in enumerate(lines[1:], start=1):
    parts = line.split("\t")
    q_index = parts[0]
    comment_id = parts[1]
    author_hash = parts[2]
    reactions = parts[3]
    quoted_id = parts[4]
    raw_text = parts[5] if len(parts) > 5 else ""

    p = parse_comment_text(raw_text)
    if p.answers:
        status = f"-> ANSWERS: {p.answers}"
    elif p.is_agreement:
        status = "-> AGREEMENT"
    else:
        status = "-> AMBIGUOUS / NO ANSWER"
        unparsed_count += 1

    print(f"[{i:02d}] Q{q_index} (author={author_hash}, rx={reactions}): '{raw_text[:50]}' {status}")

print(f"\nTotal: {len(lines) - 1} comments.")
print(f"Successfully extracted answer/agreement: {len(lines) - 1 - unparsed_count}/{len(lines) - 1}")
print(f"Ambiguous: {unparsed_count}")

