import re
import sqlite3
from collections import defaultdict
from pathlib import Path

def extract_thread_id(url):
    if not url:
        return None
    m = re.search(r"/threads/(?:[^\/.]+\.)?(\d+)", url)
    return m.group(1) if m else None

def clean_title(title):
    if not title:
        return ""
    t = re.sub(r"^\(\d+\)\s*", "", title.strip())
    t = re.sub(r"\s*\|\s*FuOverflow\s*Community.*$", "", t, flags=re.I).strip()
    badge_regex = r"^(?:\[?(?:Đề\s*Thi\s*FE|Đề\s*Thi\s*PE|Đề\s*thi\s*FE|Đề\s*thi\s*PE|Tài\s*Liệu|Tài\s*liệu)\]?[\s\-_:]*)+"
    t = re.sub(badge_regex, "", t, flags=re.I).strip()
    return t

def canonical_url(url):
    if not url:
        return url
    clean = url.split("?")[0].rstrip("/")
    if clean.endswith("/unread"):
        clean = clean[:-7]
    return clean + "/"

def main():
    db_path = Path("data/docxstacked.db")
    if not db_path.exists():
        print(f"Error: {db_path} does not exist!")
        return

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT id, subject_id, title, url, question_count, status, created_at FROM exams")
    all_exams = cur.fetchall()

    print(f"Total exams in DB before: {len(all_exams)}")

    thread_groups = defaultdict(list)
    for ex in all_exams:
        tid = extract_thread_id(ex[3])
        if tid:
            thread_groups[tid].append(ex)

    duplicates = {tid: ex_list for tid, ex_list in thread_groups.items() if len(ex_list) > 1}
    print(f"Found {len(duplicates)} duplicate thread groups:")
    for tid, ex_list in duplicates.items():
        print(f"\n--- Thread ID: {tid} ({len(ex_list)} records) ---")
        for ex in ex_list:
            cur.execute("SELECT COUNT(*) FROM questions WHERE exam_id = ?", (ex[0],))
            q_cnt = cur.fetchone()[0]
            print(f"  [Before] ID: {ex[0]} | Title: {ex[2]} | Count: {ex[4]} | DB Questions: {q_cnt} | Status: {ex[5]} | URL: {ex[3]}")

        # Decide which record to keep
        # Prioritize record with DB questions > 0, status == 'CRAWLED'
        sorted_records = sorted(
            ex_list,
            key=lambda e: (
                1 if e[5] == "CRAWLED" else 0,
                e[4],
                e[0],
            ),
            reverse=True,
        )
        winner = sorted_records[0]
        losers = sorted_records[1:]

        # Merge / update winner
        new_title = clean_title(winner[2])
        # If winner title is cleaner in one of the other records, use that
        for other in losers:
            candidate = clean_title(other[2])
            if candidate and not candidate.startswith("Đề Thi") and len(candidate) < len(new_title):
                new_title = candidate

        new_url = canonical_url(winner[3])
        cur.execute("SELECT COUNT(*) FROM questions WHERE exam_id = ?", (winner[0],))
        winner_db_q = cur.fetchone()[0]
        new_q_count = max(winner[4], winner_db_q, max((o[4] for o in losers), default=0))

        # Check if winner url already exists on another row
        cur.execute("SELECT id FROM exams WHERE url = ? AND id != ?", (new_url, winner[0]))
        colliding = cur.fetchone()
        if colliding and colliding[0] in [l[0] for l in losers]:
            cur.execute("DELETE FROM exams WHERE id = ?", (colliding[0],))

        cur.execute(
            "UPDATE exams SET title = ?, url = ?, question_count = ? WHERE id = ?",
            (new_title, new_url, new_q_count, winner[0]),
        )

        for loser in losers:
            if loser[0] != (colliding[0] if colliding else None):
                # Re-point any questions/comments if loser had questions
                cur.execute("UPDATE questions SET exam_id = ? WHERE exam_id = ?", (winner[0], loser[0]))
                cur.execute("DELETE FROM exams WHERE id = ?", (loser[0],))

        cur.execute("SELECT id, title, url, question_count, status FROM exams WHERE id = ?", (winner[0],))
        after_w = cur.fetchone()
        print(f"  [After Merge] Kept ID: {after_w[0]} | Title: {after_w[1]} | Count: {after_w[3]} | Status: {after_w[4]} | URL: {after_w[2]}")
        print(f"  [After Merge] Removed IDs: {[l[0] for l in losers]}")

    conn.commit()

    cur.execute("SELECT COUNT(*) FROM exams")
    total_after = cur.fetchone()[0]
    print(f"\nTotal exams in DB after deduplication: {total_after}")
    conn.close()

if __name__ == "__main__":
    main()
