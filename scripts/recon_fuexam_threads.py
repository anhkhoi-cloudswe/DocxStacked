"""
scripts/recon_fuexam_threads.py
Tải toàn bộ ảnh và bình luận cho 3 đề: 1174, 1587, 941.
Lưu cache chuẩn vào data/cache/fuexam/media_{media_id}/
"""

import time
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.modules.crawler.fuexam_crawler import (
    get_authenticated_session,
    extract_thread_questions,
    fetch_and_cache_media_image,
    fetch_and_cache_media_comments,
)

def crawl_exam(thread_id: int):
    session = get_authenticated_session()
    url = f"https://fuexam.me/threads/{thread_id}/"
    print(f"[*] Crawling thread {thread_id}: {url}")
    title, questions = extract_thread_questions(url, session)
    print(f"[*] Thread title: {title}, total questions: {len(questions)}")

    downloaded_img = 0
    downloaded_comms = 0
    cached_img = 0
    cached_comms = 0

    for q in questions:
        m_id = q["media_id"]
        slug = q["slug"]
        att_url = q["attachment_url"]

        img_path, was_cached = fetch_and_cache_media_image(m_id, att_url, slug, session)
        if was_cached:
            cached_img += 1
        else:
            downloaded_img += 1

        comms, c_cached = fetch_and_cache_media_comments(m_id, slug, session)
        if c_cached:
            cached_comms += 1
        else:
            downloaded_comms += 1

        print(f"  [Q{q['index']:02d}] media_id={m_id} img_cached={was_cached} comms_cached={c_cached} comms_count={len(comms)}")

    print(f"[✓] Done thread {thread_id}: {len(questions)} questions. Img: {downloaded_img} dl, {cached_img} cache. Comms: {downloaded_comms} dl, {cached_comms} cache.")

if __name__ == "__main__":
    for th in [1174, 1587, 941]:
        crawl_exam(th)

