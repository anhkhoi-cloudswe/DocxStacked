"""
Script to compare 60 questions: real comments from extension payload vs DB comments,
and print comparison table as required by Task 4.
"""
import glob
import json
import sqlite3
from pathlib import Path


def compare_60_questions():
    payload_files = sorted(glob.glob("data/ingest_debug/payload_MLN122_*.json"))
    if not payload_files:
        print("No ingest debug payloads found in data/ingest_debug/")
        return

    latest_payload_file = payload_files[-1]
    with open(latest_payload_file, "r", encoding="utf-8") as f:
        ext_payload = json.load(f)

    ext_comments_by_idx = {q["index"]: len(q.get("comments", [])) for q in ext_payload["questions"]}

    conn = sqlite3.connect("data/docxstacked.db")
    c = conn.cursor()
    c.execute("""
        SELECT q.[index], count(c.id)
        FROM questions q
        LEFT JOIN comments c ON c.question_id = q.id
        WHERE q.exam_id = 136
        GROUP BY q.[index]
        ORDER BY q.[index]
    """)
    db_counts = dict(c.fetchall())

    print("=" * 80)
    print("BẢNG SO SÁNH 60 CÂU: BÌNH LUẬN EXTENSION THU THẬP VS CƠ SỞ DỮ LIỆU")
    print(f"Exam: MLN122 - SU26 - RE (ID 136)")
    print(f"Debug Ingest File: {latest_payload_file}")
    print("=" * 80)
    print(f"{'Câu':<10} | {'Bình luận Extension':<22} | {'Bình luận DB':<20} | {'Trạng thái'}")
    print("-" * 80)

    diff_count = 0
    total_ext = 0
    total_db = 0
    for idx in range(1, 61):
        ext_c = ext_comments_by_idx.get(idx, 0)
        db_c = db_counts.get(idx, 0)
        total_ext += ext_c
        total_db += db_c
        if ext_c == db_c:
            status = "Khớp 100%"
        else:
            status = f"Lệch ({ext_c} vs {db_c})"
            diff_count += 1
        print(f"Câu {idx:<6} | {ext_c:<22} | {db_c:<20} | {status}")

    print("=" * 80)
    print(f"TỔNG KẾT: 60/60 câu. Khớp: {60 - diff_count}/60. Lệch: {diff_count}. Tổng số bình luận: {total_ext}.")
    print("=" * 80)


if __name__ == "__main__":
    compare_60_questions()
