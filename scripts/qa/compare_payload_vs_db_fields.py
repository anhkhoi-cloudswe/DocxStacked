"""
Compare comments field-by-field between extension payload (payload_*.json)
and original DB comments for all 60 questions:
- author (id/username/hash)
- content (raw_text)
- timestamp (posted_at)
- reactions/upvotes (upvotes)
- parent/reply (is_reply, quoted_comment_id)
- order / count
Print table of differing questions and differing fields, with count per field.
"""
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from backend.app.modules.crawler.comments import parse_comments_from_html


def run_field_comparison():
    # 1. Load latest extension payload
    payload_files = sorted(glob.glob("data/ingest_debug/payload_MLN122_*.json"))
    assert payload_files, "No payload files found!"
    target_payload = "data/ingest_debug/payload_MLN122_20261115_001418.json"
    if target_payload not in payload_files:
        target_payload = payload_files[-1]

    print(f"=== ĐỐI SOÁT TRƯỜNG DỮ LIỆU BÌNH LUẬN: EXTENSION PAYLOAD VS DB GỐC ===")
    print(f"Exam: MLN122 - SU26 - RE (60 câu hỏi)")
    print(f"File payload extension: {target_payload}")
    print("=" * 85)

    with open(target_payload, "r", encoding="utf-8") as f:
        payload_data = json.load(f)

    payload_questions = {q["index"]: q for q in payload_data["questions"]}

    # 2. Extract original DB comments from raw HTML files
    raw_dir = Path("data/raw/MLN122/exam_136_SU26/comments")
    diff_table = []
    field_diff_counts = {
        "author": 0,
        "content": 0,
        "timestamp": 0,
        "upvotes": 0,
        "parent_reply": 0,
        "count_order": 0,
    }

    total_ext_comments = 0
    total_db_comments = 0

    for q_idx in range(1, 61):
        q_payload = payload_questions.get(q_idx, {})
        ext_comments = q_payload.get("comments", [])
        total_ext_comments += len(ext_comments)

        html_files = list(raw_dir.glob(f"q{q_idx:03d}_*.html"))
        if not html_files:
            continue
        html_str = html_files[0].read_text(encoding="utf-8")
        db_comments = parse_comments_from_html(html_str, question_id=q_idx)
        total_db_comments += len(db_comments)

        diffs = []

        # Check count
        if len(ext_comments) != len(db_comments):
            diffs.append(f"count: ext={len(ext_comments)} vs db={len(db_comments)}")
            field_diff_counts["count_order"] += 1

        # Check each comment
        has_author_diff = False
        has_content_diff = False
        has_time_diff = False
        has_upvote_diff = False
        has_reply_diff = False

        for i in range(min(len(ext_comments), len(db_comments))):
            ec = ext_comments[i]
            dc = db_comments[i]

            # Author check
            e_author = ec.get("author_name") or ec.get("author_hash")
            d_author = dc.author_hash
            if not e_author or e_author == "Anonymous" or ec.get("author_name") is None:
                has_author_diff = True

            # Content check
            e_text = (ec.get("raw_text") or "").strip()
            d_text = (dc.raw_text or "").strip()
            if e_text != d_text:
                has_content_diff = True

            # Timestamp check
            e_time = ec.get("posted_at")
            d_time = getattr(dc, "posted_at", None)
            if e_time != d_time:
                has_time_diff = True

            # Upvotes check
            e_up = ec.get("upvotes", 0)
            d_up = dc.upvotes
            if e_up != d_up:
                has_upvote_diff = True

            # Parent / reply check
            e_rep = ec.get("is_reply", False)
            d_rep = dc.is_reply
            if e_rep != d_rep:
                has_reply_diff = True

        if has_author_diff:
            diffs.append("author (None/hash thiếu)")
            field_diff_counts["author"] += 1
        if has_content_diff:
            diffs.append("content (khác chữ)")
            field_diff_counts["content"] += 1
        if has_time_diff:
            diffs.append("timestamp (None)")
            field_diff_counts["timestamp"] += 1
        if has_upvote_diff:
            diffs.append("upvotes (rx=0)")
            field_diff_counts["upvotes"] += 1
        if has_reply_diff:
            diffs.append("parent/reply")
            field_diff_counts["parent_reply"] += 1

        if diffs:
            diff_table.append((q_idx, len(ext_comments), len(db_comments), ", ".join(diffs)))

    # Print summary table
    print(f"{'Câu':<8} | {'SL Ext':<8} | {'SL DB':<8} | {'Các trường khác biệt'}")
    print("-" * 85)
    for q_idx, ec_len, dc_len, diff_desc in diff_table:
        print(f"Câu {q_idx:<4} | {ec_len:<8} | {dc_len:<8} | {diff_desc}")

    print("-" * 85)
    print(f"\n=== TỔNG KẾT ĐẾM SAI LỆCH THEO TỪNG TRƯỜNG DỮ LIỆU (TRÊN 60 CÂU) ===")
    print(f"  * Tổng số câu có khác biệt         : {len(diff_table)}/60 câu")
    print(f"  * Tổng bình luận Ext vs DB          : {total_ext_comments} vs {total_db_comments}")
    print(f"  * Số câu sai trường author (người đăng) : {field_diff_counts['author']}/60 câu")
    print(f"  * Số câu sai trường timestamp (thời gian) : {field_diff_counts['timestamp']}/60 câu")
    print(f"  * Số câu sai trường upvotes (reactions) : {field_diff_counts['upvotes']}/60 câu")
    print(f"  * Số câu sai trường parent/reply        : {field_diff_counts['parent_reply']}/60 câu")
    print(f"  * Số câu sai trường content (nội dung)  : {field_diff_counts['content']}/60 câu")
    print(f"  * Số câu sai số lượng / thứ tự          : {field_diff_counts['count_order']}/60 câu")
    print("=" * 85)


if __name__ == "__main__":
    run_field_comparison()
