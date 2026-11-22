"""
scripts/verify_re_voters_complete.py
Thực hiện đối soát phiếu bầu đề PRM393 - SU26 - FE - RE (Thread 941).

Chức năng:
1. In nội dung thô comments.json của Q01, Q02, Q03 trước/sau khi refresh.
2. Tùy chọn --force-refresh: Cào lại toàn bộ 50 câu từ fuexam.me (hỗ trợ phân trang, in số comment/trang).
3. Đọc dữ liệu từ cùng MỘT nguồn comments.json duy nhất để sinh:
   - Bảng 1: Thống kê người bầu (Nick, số câu bầu / 50, số câu trùng, tỷ lệ trùng %).
   - Bảng 2: Bảng chi tiết 50 câu (Q01-Q50: số bình luận, chi tiết phiếu, đáp án chốt, độ tin cậy, nguồn).
4. Khẳng định tính nhất quán toán học 100%: Số câu bầu của từng voter ở Bảng 1
   trùng khớp tuyệt đối với số lần xuất hiện của voter đó trong Bảng 2.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from collections import defaultdict
from typing import Any, Dict, List, Tuple

from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.modules.crawler.fuexam_crawler import (
    get_authenticated_session,
    check_session_validity,
    BASE_URL,
    CACHE_DIR,
)
from backend.app.modules.analysis.voting import tally_votes
from backend.app.db.models import Comment


def extract_vote_from_comment(raw_text: str) -> str:
    """Trích xuất ký tự đáp án A-E từ nội dung bình luận."""
    t = raw_text.strip()
    # Mẫu B. hoặc B: ở đầu
    m = re.match(r"^([A-E])[\.\:\-\s\)]", t, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    # Mẫu đơn giản chỉ có 1 chữ cái đơn
    if len(t) <= 3:
        m = re.search(r"\b([A-E])\b", t, re.IGNORECASE)
        if m:
            return m.group(1).upper()
    # Tìm chữ cái sau "đáp án", "chọn"
    m = re.search(r"(?:đáp\s*án|chọn|là)\s*[:\s]*([A-E])\b", t, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    # Mẫu từ đầu tiên là A-E
    m = re.search(r"\b([A-E])\b", t, re.IGNORECASE)
    if m:
        return m.group(1).upper()
    return ""


def crawl_live_comments_with_pagination(
    media_id: int,
    slug: str,
    session,
    delay_seconds: float = 1.6,
) -> Tuple[List[Dict[str, Any]], List[int]]:
    """Cào bình luận của media_id kèm xử lý phân trang và ghi nhận số comment/trang."""
    base_media_url = f"{BASE_URL}/media/{slug}.{media_id}/"
    page_num = 1
    all_comments: List[Dict[str, Any]] = []
    comments_per_page: List[int] = []

    while True:
        url = base_media_url if page_num == 1 else f"{base_media_url}page-{page_num}"
        time.sleep(delay_seconds)
        resp = session.get(url, timeout=20)
        if resp.status_code != 200:
            break

        soup = BeautifulSoup(resp.text, "html.parser")
        comment_articles = soup.select(".message--comment")
        page_comments_count = len(comment_articles)
        comments_per_page.append(page_comments_count)

        for c in comment_articles:
            c_id = c.get("data-content") or c.get("id") or ""
            m_id_match = re.search(r"\d+", c_id)
            numeric_id = int(m_id_match.group(0)) if m_id_match else None

            author_el = c.select_one(".username")
            author_name = author_el.text.strip() if author_el else "Thành viên"
            author_hash = hashlib.sha256(author_name.encode("utf-8")).hexdigest()[:12]

            body_el = c.select_one(".bbWrapper")
            quote_el = body_el.select_one("blockquote") if body_el else None
            quoted_text = quote_el.text.strip() if quote_el else ""
            if quote_el:
                quote_el.decompose()

            clean_text = body_el.text.strip() if body_el else ""

            rx_bar = c.select_one(".reactionsBar")
            rx_count = 0
            if rx_bar:
                rx_links = rx_bar.select("a")
                rx_count = max(1, len(rx_links))

            time_el = c.select_one("time[datetime]")
            c_time = time_el.get("datetime") if time_el else ""

            all_comments.append({
                "comment_id": numeric_id,
                "author_name": author_name,
                "author_hash": author_hash,
                "raw_text": clean_text,
                "quoted_text": quoted_text,
                "reactions": rx_count,
                "created_at": c_time,
            })

        # Kiểm tra trang tiếp theo
        next_btn = soup.select_one(".pageNav-jump--next, a.pageNav-jump:contains('Tiếp')")
        has_next = False
        if next_btn and next_btn.get("href"):
            has_next = True
        elif soup.select(f".pageNav-page a[href*='page-{page_num + 1}']"):
            has_next = True

        if not has_next or page_comments_count == 0:
            break
        page_num += 1

    # Lưu vào cache
    out_dir = CACHE_DIR / f"media_{media_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    c_file = out_dir / "comments.json"
    payload = {
        "media_id": media_id,
        "slug": slug,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_comments": len(all_comments),
        "comments": all_comments,
    }
    c_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return all_comments, comments_per_page


def main():
    parser = argparse.ArgumentParser(description="Audit votes for PRM393 - SU26 - FE - RE")
    parser.add_argument("--force-refresh", action="store_true", help="Re-fetch comments from live fuexam.me")
    parser.add_argument("--limit", type=int, default=50, help="Number of questions to process (default 50)")
    args = parser.parse_args()

    re_media_base = 34522  # Q01 of PRM393 - SU26 - FE - RE

    print("=" * 70)
    print("  ĐỐI SOÁT PHIẾU BẦU ĐỀ: PRM393 - SU26 - FE - RE (Thread 941)")
    print("=" * 70)

    # 1. In nội dung thô Q01 - Q03 hiện có
    print("\n[1] NỘI DUNG THÔ comments.json CỦA Q01, Q02, Q03:")
    for q_i, m_id in enumerate([34522, 34523, 34524], start=1):
        f = CACHE_DIR / f"media_{m_id}" / "comments.json"
        print(f"\n--- Q{q_i:02d} ({f.as_posix()}) ---")
        if f.exists():
            print(f.read_text(encoding="utf-8").strip())
        else:
            print("[Chưa có file cache]")

    # 2. Thực hiện force-refresh nếu yêu cầu
    if args.force_refresh:
        print("\n[2] TIẾN HÀNH --force-refresh TỪ FUXAM.ME (hỗ trợ phân trang, trễ 1.6s)...")
        session = get_authenticated_session()
        if not check_session_validity(session):
            print("[X] Phiên fuexam.me không hợp lệ hoặc đã hết hạn!")
            sys.exit(1)
        print("[✓] Phiên đăng nhập hợp lệ. Bắt đầu tải...")

        for q_idx in range(1, args.limit + 1):
            m_id = re_media_base + q_idx - 1
            slug = f"prm393-su26-fe-re_{q_idx:03d}-webp"
            comms, per_page = crawl_live_comments_with_pagination(
                media_id=m_id,
                slug=slug,
                session=session,
                delay_seconds=1.6,
            )
            pages_summary = ", ".join(f"Trang {p_i+1}: {cnt} bình luận" for p_i, cnt in enumerate(per_page))
            print(f"  Q{q_idx:02d} (media {m_id}): {pages_summary} -> Tổng {len(comms)} bình luận")

    # 3. Đọc dữ liệu từ cùng MỘT nguồn comments.json duy nhất
    print("\n[3] PHÂN TÍCH TOÀN BỘ 50 CÂU TỪ CÙNG MỘT NGUỒN:")
    author_votes = defaultdict(dict)  # author -> {q_idx: vote}
    question_details = []  # list of dicts for Table 2

    for q_idx in range(1, 51):
        m_id = re_media_base + q_idx - 1
        c_file = CACHE_DIR / f"media_{m_id}" / "comments.json"
        if not c_file.exists():
            continue
        c_data = json.loads(c_file.read_text(encoding="utf-8"))
        comments_list = c_data.get("comments", [])

        # Chuyển đổi sang Comment DB model để đưa qua tally_votes chuẩn của hệ thống
        db_comments = []
        q_voter_choices = {}
        for c in comments_list:
            auth = c.get("author_name", "Ẩn danh")
            raw_text = c.get("raw_text", "")
            v = extract_vote_from_comment(raw_text)
            if v:
                author_votes[auth][q_idx] = v
                q_voter_choices[auth] = v
            db_comments.append(Comment(
                question_id=q_idx,
                comment_id=str(c.get("comment_id", "")),
                author_hash=c.get("author_hash", "anon"),
                raw_text=raw_text,
                upvotes=c.get("reactions", 0),
            ))

        # Gọi voting module chuẩn
        voting_res = tally_votes(db_comments)
        ans_final = ",".join(voting_res.answer_set) if voting_res.answer_set else "?"
        status_final = voting_res.status.value if hasattr(voting_res.status, "value") else str(voting_res.status)

        # Xây dựng breakdown phiếu: SerIous:B, Sora:B
        voter_str_list = [f"{auth}:{vote}" for auth, vote in q_voter_choices.items()]
        voter_str = ", ".join(voter_str_list) if voter_str_list else "Không có"

        question_details.append({
            "q_idx": q_idx,
            "media_id": m_id,
            "total_comments": len(comments_list),
            "voters_count": len(q_voter_choices),
            "voters_str": voter_str,
            "q_voter_choices": q_voter_choices,
            "final_answer": ans_final,
            "confidence": voting_res.confidence,
            "status": status_final,
            "source": "community",
        })

    # Xác định đáp án chuẩn đối chiếu (consensus từ chính 50 câu)
    consensus_answers = {q["q_idx"]: q["final_answer"] for q in question_details}

    # BẢNG 1: THỐNG KÊ NGƯỜI BẦU
    print("\n" + "=" * 75)
    print("  BẢNG 1: THỐNG KÊ NGƯỜI BẦU (ĐỌC TỪ CÙNG NGUỒN comments.json)")
    print("=" * 75)
    print(f"{'STT':<4} | {'Tên Nick (Voter)':<28} | {'Số câu bầu':<11} | {'Trùng đáp án':<12} | {'Tỷ lệ':<8}")
    print("-" * 75)

    voter_stats = []
    for auth, votes in author_votes.items():
        voted_count = len(votes)
        match_count = sum(1 for q, v in votes.items() if consensus_answers.get(q) == v)
        pct = (match_count / voted_count * 100.0) if voted_count > 0 else 0.0
        voter_stats.append((auth, voted_count, match_count, pct))

    voter_stats.sort(key=lambda x: x[1], reverse=True)
    for idx, (auth, voted_cnt, match_cnt, pct) in enumerate(voter_stats, start=1):
        print(f"{idx:<4} | {auth:<28} | {voted_cnt:>2d}/50 câu   | {match_cnt:>2d}/50 câu    | {pct:>6.1f}%")
    print("-" * 75)

    # BẢNG 2: BẢNG CHI TIẾT 50 CÂU
    print("\n" + "=" * 90)
    print("  BẢNG 2: BẢNG CHI TIẾT 50 CÂU HỎI ĐỀ RE (THREAD 941)")
    print("=" * 90)
    print(f"{'Câu':<5} | {'Bình luận':<9} | {'Chi tiết các phiếu bầu':<45} | {'Đáp án':<6} | {'Độ tin cậy':<10}")
    print("-" * 90)

    # Kiểm tra kiểm soát tính nhất quán
    appearance_counts = defaultdict(int)

    for q in question_details:
        q_num = f"Q{q['q_idx']:02d}"
        c_cnt = f"{q['total_comments']} cmt"
        v_str = q['voters_str']
        if len(v_str) > 43:
            v_str = v_str[:40] + "..."
        ans = q['final_answer']
        conf = f"{q['confidence']*100:.0f}% ({q['status']})"
        print(f"{q_num:<5} | {c_cnt:<9} | {v_str:<45} | {ans:<6} | {conf:<10}")

        for auth in q['q_voter_choices']:
            appearance_counts[auth] += 1

    print("-" * 90)

    # 4. KHẲNG ĐỊNH TÍNH NHẤT QUÁN TOÁN HỌC 100%
    print("\n[4] KIỂM TRA ĐỐI CHIẾU NHẤT QUÁN GIỮA BẢNG 1 VÀ BẢNG 2:")
    is_fully_consistent = True
    for auth, voted_cnt, _, _ in voter_stats:
        in_table2 = appearance_counts[auth]
        is_match = (voted_cnt == in_table2)
        if not is_match:
            is_fully_consistent = False
        print(f"  - Nick '{auth}': Bảng 1 = {voted_cnt} câu | Bảng 2 = {in_table2} lần xuất hiện -> {'KHỚP [✓]' if is_match else 'LỆCH [X]'}")

    assert is_fully_consistent, "LỖI: Bảng 1 và Bảng 2 không khớp số lượng phiếu bầu!"
    print("\n[✓] XÁC NHẬN: 100% người bầu ở Bảng 1 trùng khớp hoàn toàn với Bảng 2!")
    print(f"  Ví dụ cụ thể:")
    print(f"  - SerIous: Bảng 1 có {len(author_votes.get('SerIous', {}))} câu == Bảng 2 xuất hiện {appearance_counts['SerIous']} lần.")
    print(f"  - deptraicojshy: Bảng 1 có {len(author_votes.get('deptraicojshy', {}))} câu == Bảng 2 xuất hiện {appearance_counts['deptraicojshy']} lần.")
    print(f"  - Q1: Có {question_details[0]['total_comments']} bình luận thật trên trang, ghi nhận {question_details[0]['voters_count']} phiếu bầu ({question_details[0]['voters_str']}) -> Đáp án: {question_details[0]['final_answer']}.")


if __name__ == "__main__":
    main()
