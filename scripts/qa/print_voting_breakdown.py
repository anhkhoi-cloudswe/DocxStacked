"""
Print voting breakdown comparison table for Q1, Q22, Q32, Q52, Q56
according to two sources:
1. Extension payload (with missing/collapsed authors)
2. DB cu / Playwright crawler (with distinct authors & reactions)
"""
import glob
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from backend.app.modules.crawler.comments import parse_comments_from_html
from backend.app.modules.analysis.voting import tally_votes


class DummyComment:
    def __init__(self, raw_text, author_hash, upvotes=0, is_reply=False, quoted_comment_id=None, comment_id="1"):
        self.id = 1
        self.comment_id = comment_id
        self.raw_text = raw_text
        self.author_hash = author_hash
        self.upvotes = upvotes
        self.is_reply = is_reply
        self.quoted_comment_id = quoted_comment_id


def compare_voting_breakdown():
    # 1. Load extension payload
    payload_file = "data/ingest_debug/payload_MLN122_20261115_001418.json"
    with open(payload_file, "r", encoding="utf-8") as f:
        payload_data = json.load(f)
    ext_q_map = {q["index"]: q for q in payload_data["questions"]}

    raw_dir = Path("data/raw/MLN122/exam_136_SU26/comments")

    target_qs = [1, 22, 32, 52, 56]

    print("=" * 105)
    print("BẢNG SO SÁNH BỎ PHIẾU CHO Q1, Q22, Q32, Q52, Q56 THEO HAI NGUỒN")
    print("Nguồn 1: Extension Payload (lỗi thiếu author -> gộp thành 1 người)")
    print("Nguồn 2: DB Cũ / Crawler Chuẩn (đủ người đăng độc lập & trọng số)")
    print("=" * 105)

    headers = [
        "Câu",
        "Nguồn Ext: ĐA",
        "Ext: Status",
        "Ext: Voters",
        "Ext: Weight",
        "Nguồn DB: ĐA",
        "DB: Status",
        "DB: Voters",
        "DB: Weight",
        "Lý do sai lệch",
    ]
    fmt = "| {:<5} | {:<12} | {:<11} | {:<10} | {:<10} | {:<12} | {:<10} | {:<10} | {:<10} | {:<22} |"
    print(fmt.format(*headers))
    print("|" + "|".join(["-" * (len(h) + 2) for h in headers]) + "|")

    for q_idx in target_qs:
        # Source 1: Extension payload (simulating ingest with collapsed author e7a8aa2df7e5d0b2)
        q_ext = ext_q_map.get(q_idx, {})
        ext_comms_collapsed = []
        for c in q_ext.get("comments", []):
            ext_comms_collapsed.append(DummyComment(
                raw_text=c["raw_text"],
                author_hash="e7a8aa2df7e5d0b2",  # All collapsed to same hash
                upvotes=c.get("upvotes", 0),
                is_reply=c.get("is_reply", False),
            ))
        res_ext = tally_votes(ext_comms_collapsed)

        # Source 2: DB cu / real comments from HTML
        html_files = list(raw_dir.glob(f"q{q_idx:03d}_*.html"))
        assert html_files, f"HTML file for Q{q_idx} missing!"
        db_comms = parse_comments_from_html(html_files[0].read_text(encoding="utf-8"), question_id=q_idx)
        res_db = tally_votes(db_comms)

        ans_ext_str = ", ".join(res_ext.answer_set)
        ans_db_str = ", ".join(res_db.answer_set)

        # Reason analysis
        reasons = []
        if res_ext.voters_count < res_db.voters_count:
            reasons.append(f"Voters {res_ext.voters_count}->{res_db.voters_count}")
        if res_ext.status != res_db.status:
            reasons.append(f"Status {res_ext.status.value}->{res_db.status.value}")
        if ans_ext_str != ans_db_str:
            reasons.append(f"ĐA {ans_ext_str}->{ans_db_str}")
        reason_str = "; ".join(reasons) if reasons else "Khớp hoàn toàn"

        row = [
            f"Q{q_idx}",
            ans_ext_str,
            res_ext.status.value.upper(),
            f"{res_ext.voters_count} ng",
            f"{res_ext.total_weight:.2f}",
            ans_db_str,
            res_db.status.value.upper(),
            f"{res_db.voters_count} ng",
            f"{res_db.total_weight:.2f}",
            reason_str,
        ]
        print(fmt.format(*row))

    print("=" * 105)
    print("\n### NGUYÊN NHÂN CỐT LÕI KHIẾN MỌI CÂU THÀNH WEAK / CONFLICT:")
    print("1. Thiếu thông tin author: Trong payload extension cũ, author_name bị None. Backend fallback về")
    print("   hashlib.sha256('Anonymous') dẫn tới TOÀN BỘ 206 bình luận của 60 câu đều mang cùng 1 author_hash.")
    print("2. Cơ chế chống spam/deduplicate của voting.py: Khi các bình luận có cùng author_hash, hàm bỏ phiếu")
    print("   chỉ tính là 1 cử tri duy nhất (voters_count = 1).")
    print("3. Điều kiện trạng thái tự động biến thành WEAK: voting.py dòng 352 quy định:")
    print("   'if confidence >= 0.70 and winner_independent_voters >= 2: status = CONFIDENT else: status = WEAK'")
    print("   Vì winner_independent_voters = 1 < 2, NÊN TẤT CẢ 60/60 CÂU ĐỀU BỊ ĐÁNH DẤU WEAK ('cần kiểm tra lại')!")
    print("4. Mất trọng số reactions: Khi các bình luận bị gộp, tổng trọng số bị thu nhỏ về 1 phiếu và mất các")
    print("   lượt upvotes của từng người riêng biệt -> Làm thay đổi kết quả câu Q52 (A lật sang B), Q32 mất từ khóa.")
    print("=" * 105)


if __name__ == "__main__":
    compare_voting_breakdown()
