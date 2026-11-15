"""
Test end-to-end extension collection on MLN122 - SU26 - RE without entering token:
1. Ping GET /api/ingest/ping from pinned extension Origin without token -> 200 OK
2. Extract all 60 questions & comments with real authors, upvotes, timestamps
3. Ingest into backend POST /api/ingest with pinned extension Origin and NO token
4. Verify Word docx generation and print full execution logs
"""
import base64
import json
from pathlib import Path
import re
import sys
import time
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from backend.app.main import app
from backend.app.core.config import get_settings

settings = get_settings()
client = TestClient(app)


def run_real_extension_ingest_no_token():
    print("=" * 90)
    print("CHẠY THU THẬP VÀ INGEST ĐỀ MLN122 - SU26 - RE TỪ EXTENSION (KHÔNG NHẬP TOKEN)")
    print(f"Pinned Extension ID: {settings.EXTENSION_ID}")
    print(f"Origin             : chrome-extension://{settings.EXTENSION_ID}")
    print("=" * 90)

    # 1. Ping test without token
    print("\n[BƯỚC 1] Extension gọi GET /api/ingest/ping kiểm tra backend trước khi cào...")
    ping_res = client.get(
        "/api/ingest/ping",
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": f"chrome-extension://{settings.EXTENSION_ID}",
        },
    )
    print(f"  -> Ping HTTP Status: {ping_res.status_code}")
    print(f"  -> Ping Response   : {ping_res.json()}")
    assert ping_res.status_code == 200, f"Ping failed with status {ping_res.status_code}"
    print("  [XÁC THỰC THÀNH CÔNG] Extension đã ghim ID được backend chấp nhận trực tiếp không cần token!")

    # 2. Extract 60 questions and comments from raw media HTMLs (simulating extension sidepanel)
    print("\n[BƯỚC 2] Bắt đầu bóc tách 60 câu hỏi và bình luận theo chuẩn Extension...")
    raw_dir = Path("data/raw/MLN122/exam_136_SU26/comments")
    img_dir = Path("data/raw/MLN122/exam_136_SU26")
    assert raw_dir.exists(), "Raw comments directory not found!"

    questions_payload = []
    total_comments_count = 0

    for q_idx in range(1, 61):
        html_files = list(raw_dir.glob(f"q{q_idx:03d}_*.html"))
        assert html_files, f"HTML file for Q{q_idx} missing!"
        soup = BeautifulSoup(html_files[0].read_text(encoding="utf-8"), "html.parser")

        # Extract image base64
        img_p = img_dir / f"q{q_idx:02d}_Q{q_idx}.webp"
        b64_data = ""
        if img_p.exists():
            b64_data = base64.b64encode(img_p.read_bytes()).decode("utf-8")
        else:
            b64_data = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

        c_list = []
        for c in soup.select(".message--comment, .message--mediaComment, .js-comment"):
            raw_id = c.get("data-content") or c.get("id") or ""
            m_id = re.search(r"\d+", raw_id)
            cid = m_id.group(0) if m_id else None

            # Author name
            author_el = c.select_one(".message-name, .comment-user, .username, .comment-author")
            author_name = author_el.get_text(strip=True) if author_el else (c.get("data-author") or "Unknown")

            # Reactions
            rx_bar = c.select_one(".reactionsBar")
            upvotes = 0
            if rx_bar:
                rx_text = rx_bar.get_text(" ", strip=True)
                bdis = rx_bar.select("a.reactionsBar-link bdi, .reactionsBar bdi")
                m_oth = re.search(r"(?:and|và)\s+(\d+)\s+(?:others|người khác)", rx_text, re.I)
                others_count = int(m_oth.group(1)) if m_oth else 0
                m_total = re.search(r"(\d+)\s+(?:reactions|lượt thích|phản ứng)", rx_text, re.I)
                if m_total:
                    upvotes = int(m_total.group(1))
                elif len(bdis) > 0 or others_count > 0:
                    upvotes = len(bdis) + others_count
                elif rx_bar.select(".reaction-image, .reaction[data-reaction-id]"):
                    upvotes = 1

            # Quote block
            quote_block = c.select_one("blockquote, .bbCodeBlock--quote")
            quoted_id = None
            is_reply = bool(quote_block)
            if quote_block:
                title_link = quote_block.select_one(".bbCodeBlock-title a")
                if title_link and title_link.get("href"):
                    m_q = re.search(r"/comments/(\d+)", title_link.get("href"))
                    if m_q:
                        quoted_id = int(m_q.group(1))

            # Timestamp
            time_el = c.select_one("time.u-dt, time")
            posted_at = None
            if time_el:
                posted_at = time_el.get("datetime") or time_el.get("data-date") or time_el.get_text(strip=True)

            # Raw text
            bb = c.select_one(".message-body .bbWrapper, .message-body, .comment-content")
            raw_text = ""
            if bb:
                bb_copy = BeautifulSoup(str(bb), "html.parser").find()
                for qb in bb_copy.select("blockquote, .bbCodeBlock--quote"):
                    qb.decompose()
                raw_text = bb_copy.get_text(" ", strip=True)

            if raw_text:
                c_list.append({
                    "comment_id": cid,
                    "author_name": author_name,
                    "raw_text": raw_text,
                    "upvotes": upvotes,
                    "quoted_comment_id": quoted_id,
                    "is_reply": is_reply,
                    "posted_at": posted_at,
                })

        total_comments_count += len(c_list)
        questions_payload.append({
            "index": q_idx,
            "file_name": f"Q{q_idx}.webp",
            "media_id": f"media_{q_idx}",
            "media_url": f"https://fuoverflow.com/media/q{q_idx}-webp.{q_idx}/",
            "image_base64": b64_data,
            "comments": c_list,
        })

    print(f"  -> Đã bóc tách thành công 60 câu hỏi với tổng cộng {total_comments_count} bình luận!")
    print(f"  -> Q1 : {len(questions_payload[0]['comments'])} bình luận (Tác giả: {', '.join(c['author_name'] for c in questions_payload[0]['comments'])})")
    print(f"  -> Q22: {len(questions_payload[21]['comments'])} bình luận")
    print(f"  -> Q52: {len(questions_payload[51]['comments'])} bình luận (Upvotes: {[c['upvotes'] for c in questions_payload[51]['comments']]})")
    print(f"  -> Q56: {len(questions_payload[55]['comments'])} bình luận")

    # 3. Post to /api/ingest without token
    print("\n[BƯỚC 3] Gửi payload tới POST /api/ingest với Origin extension và KHÔNG gửi X-Ingest-Token...")
    ingest_body = {
        "subject_code": "MLN122",
        "exam_title": "MLN122 - SU26 - RE",
        "exam_url": "https://fuoverflow.com/threads/mln122-su26-re.7207/",
        "term": "SU26",
        "exam_type": "RE",
        "questions": questions_payload,
        "options": {
            "ai_enabled": False,
        },
    }

    t0 = time.time()
    res = client.post(
        "/api/ingest",
        json=ingest_body,
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": f"chrome-extension://{settings.EXTENSION_ID}",
            # NO X-Ingest-Token!
        },
    )
    t1 = time.time()

    print(f"  -> Ingest HTTP Status: {res.status_code} (thực thi trong {t1 - t0:.2f}s)")
    assert res.status_code == 200, f"Ingest failed: {res.text}"

    data = res.json()
    print(f"  -> Trạng thái kết quả : {data.get('status')}")
    print(f"  -> Tên đề thi         : '{data.get('exam_title')}'")
    print(f"  -> Số câu đã lưu      : {data.get('questions_ingested')}/60")
    print(f"  -> Số bình luận đã lưu: {data.get('comments_ingested')}")
    print(f"  -> File Word đã tạo   : {data.get('docx_filename')}")
    print(f"  -> Đường dẫn tải về   : {data.get('download_url')}")
    print(f"  -> File path          : {data.get('docx_path')}")

    # Verify docx file on disk
    docx_file = Path(data.get("docx_path"))
    assert docx_file.exists(), f"Word document not found at {docx_file}"
    print(f"  -> Kích thước file docx: {docx_file.stat().st_size:,} bytes")
    print("\n[HOÀN THÀNH] Toàn bộ chu trình cào và ingest của extension chạy hoàn hảo mà không cần nhập token!")


if __name__ == "__main__":
    run_real_extension_ingest_no_token()
