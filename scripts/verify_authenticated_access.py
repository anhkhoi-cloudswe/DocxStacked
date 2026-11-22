"""
scripts/verify_authenticated_access.py
Xác minh toàn diện trạng thái phiên đăng nhập fuexam.me theo yêu cầu mục 2:
- html[data-logged-in] trên thread 941 và media page
- Danh sách cookie (chỉ tên + hạn, KHÔNG in giá trị)
- Tải ảnh qua /attachments/... bằng phiên (HTTP code, loại file, sha256 so với /media/.../full)
- Bình luận và reaction trên /media/... (so sánh số lượng bình luận giữa khách và đã đăng nhập trên 6 ảnh)
- Kiểm tra độ bền phiên qua 10 request liên tiếp (khoảng nghỉ >= 1.6s)
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STORAGE_STATE_FILE = PROJECT_ROOT / "data" / "auth" / "fuexam_storage_state.json"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
BASE_URL = "https://fuexam.me"


def load_authenticated_session() -> Tuple[requests.Session, List[Dict]]:
    if not STORAGE_STATE_FILE.exists():
        print(f"[X] Không tìm thấy tệp phiên: {STORAGE_STATE_FILE}")
        sys.exit(1)

    state = json.loads(STORAGE_STATE_FILE.read_text(encoding="utf-8"))
    cookies_data = state.get("cookies", [])

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    for c in cookies_data:
        # requests.cookies.set_cookie or cookie jar
        session.cookies.set(
            name=c["name"],
            value=c["value"],
            domain=c.get("domain", "").lstrip("."),
            path=c.get("path", "/"),
        )

    return session, cookies_data


def test_part_1_and_2(session: requests.Session, cookies_data: List[Dict]):
    print("=" * 80)
    print("MỤC 2.1 & 2.2: COOKIE PHIÊN VÀ THUỘC TÍNH DATA-LOGGED-IN")
    print("=" * 80)

    print("\n1. Danh sách cookie lưu trong storage_state (tuyệt đối KHÔNG in giá trị bí mật):")
    for c in cookies_data:
        name = c["name"]
        domain = c.get("domain", "N/A")
        exp = c.get("expires", -1)
        if exp and exp > 0:
            exp_dt = datetime.fromtimestamp(exp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        else:
            exp_dt = "Session (Hết hạn khi đóng phiên)"
        http_only = c.get("httpOnly", False)
        secure = c.get("secure", False)

        role = "Cookie phụ trợ"
        if name == "xf_user":
            role = "QUYẾT ĐỊNH PHIÊN DÀI HẠN (Remember Me Token)"
        elif name == "xf_session":
            role = "QUYẾT ĐỊNH PHIÊN HIỆN TẠI (Session Token)"
        elif name == "xf_csrf":
            role = "Token phòng chống tấn công chéo CSRF"

        print(f"  • Cookie: {name:<18} | Hạn dùng: {exp_dt:<24} | HttpOnly: {str(http_only):<5} | Secure: {str(secure):<5}")
        print(f"    -> Vai trò: {role}")

    # Kiểm tra data-logged-in trên Thread 941
    thread_url = "https://fuexam.me/threads/prm393-su26-fe-re.941/"
    resp_thread = session.get(thread_url, timeout=20)
    soup_thread = BeautifulSoup(resp_thread.text, "html.parser")
    thread_logged_in = soup_thread.find("html").get("data-logged-in") if soup_thread.find("html") else "N/A"
    thread_title = soup_thread.title.string.strip() if soup_thread.title else "N/A"

    print(f"\n2. Kiểm tra thuộc tính data-logged-in trên Thread 941:")
    print(f"   - URL yêu cầu: {thread_url}")
    print(f"   - Mã HTTP    : {resp_thread.status_code}")
    print(f"   - Tiêu đề    : {thread_title}")
    print(f"   - html[data-logged-in]: {thread_logged_in}")

    # Kiểm tra data-logged-in trên Media Page 34522
    media_url = "https://fuexam.me/media/prm393-su26-fe-re_001-webp.34522/"
    resp_media = session.get(media_url, timeout=20)
    soup_media = BeautifulSoup(resp_media.text, "html.parser")
    media_logged_in = soup_media.find("html").get("data-logged-in") if soup_media.find("html") else "N/A"
    media_title = soup_media.title.string.strip() if soup_media.title else "N/A"

    print(f"\n3. Kiểm tra thuộc tính data-logged-in trên Media Page 34522:")
    print(f"   - URL yêu cầu: {media_url}")
    print(f"   - Mã HTTP    : {resp_media.status_code}")
    print(f"   - Tiêu đề    : {media_title}")
    print(f"   - html[data-logged-in]: {media_logged_in}")

    return soup_thread


def test_part_3_attachment_download(session: requests.Session):
    print("\n" + "=" * 80)
    print("MỤC 2.3: TẢI ẢNH QUA /attachments/... BẰNG PHIÊN ĐĂNG NHẬP")
    print("=" * 80)

    attach_url = "https://fuexam.me/attachments/prm393-su26-fe-re_001-webp.68981/"
    print(f"Yêu cầu tải: {attach_url}")

    resp = session.get(attach_url, allow_redirects=True, timeout=25)
    status_code = resp.status_code
    final_url = resp.url
    content_type = resp.headers.get("Content-Type", "")
    content_len = len(resp.content)
    first_12 = resp.content[:12]
    sha256_hash = hashlib.sha256(resp.content).hexdigest()

    # So sánh với SHA256 đã đo trước đó tại /media/.../full
    expected_sha256 = "36bcfcb8038ccedbf3dc67f5694f2425e4012d8a30eb97fc8f6b45520cb055ef"
    is_identical = (sha256_hash == expected_sha256)

    print(f"  • Mã HTTP       : {status_code}")
    print(f"  • URL cuối      : {final_url}")
    print(f"  • Content-Type  : {content_type}")
    print(f"  • Dung lượng    : {content_len} bytes")
    print(f"  • 12 byte đầu   : {first_12} (hex: {first_12.hex()})")
    print(f"  • SHA256 tải về : {sha256_hash}")
    print(f"  • SHA256 đo trước qua /media/.../full: {expected_sha256}")
    print(f"  • Khớp 100% từng byte: {'ĐÚNG (Chính xác cùng 1 file ảnh)' if is_identical else 'KHÁC NHAU'}")


def test_part_4_comments_and_reactions(session: requests.Session, soup_thread: BeautifulSoup):
    print("\n" + "=" * 80)
    print("MỤC 2.4: BÌNH LUẬN VÀ REACTION TRÊN CÁC TRANG MEDIA")
    print("=" * 80)

    # Lấy 6 ảnh đầu tiên từ thread 941
    items = []
    previews = soup_thread.select("a.file-preview")
    for prev in previews[:6]:
        href = prev.get("href", "")
        sb_href = prev.get("data-lb-sidebar-href", "")
        # sb_href has format: /media/prm393-su26-fe-re_001-webp.34522/?lightbox=1
        m = re.search(r"/media/([^/?]+)\.?(\d+)?/?", sb_href)
        if m:
            clean_media_url = f"https://fuexam.me/media/{m.group(1)}/"
        else:
            clean_media_url = urljoin(BASE_URL, sb_href.split("?")[0])

        alt = prev.find("img").get("alt", "") if prev.find("img") else "image"
        items.append({"title": alt, "url": clean_media_url})

    guest_session = requests.Session()
    guest_session.headers.update({"User-Agent": USER_AGENT})

    print("\n1. So sánh số lượng bình luận giữa KHÁCH và ĐÃ ĐĂNG NHẬP trên 6 ảnh mẫu:")
    print(f"{'STT':<4} | {'Tên Ảnh':<30} | {'Media URL':<48} | {'Khách':<8} | {'Đã đăng nhập':<12}")
    print("-" * 115)

    reaction_examples = []

    for idx, it in enumerate(items, 1):
        url = it["url"]
        name = it["title"]

        # Request với quyền khách
        r_guest = guest_session.get(url, timeout=15)
        soup_g = BeautifulSoup(r_guest.text, "html.parser")
        comments_g = soup_g.select(".message--comment")

        # Request với phiên đăng nhập
        time.sleep(1.6)
        r_auth = session.get(url, timeout=15)
        soup_a = BeautifulSoup(r_auth.text, "html.parser")
        comments_a = soup_a.select(".message--comment")

        print(f"{idx:<4} | {name[:30]:<30} | {url[:48]:<48} | {len(comments_g):<8} | {len(comments_a):<12}")

        # Thu thập ví dụ reaction nếu có
        for c in comments_a:
            rx_bar = c.select_one(".reactionsBar")
            if rx_bar and rx_bar.text.strip():
                author = c.select_one(".username")
                auth_name = author.text.strip() if author else "N/A"
                reaction_examples.append({
                    "image": name,
                    "author": auth_name,
                    "selector": ".reactionsBar.js-reactionsList",
                    "text": rx_bar.text.strip(),
                })

    print("\n2. Kiểm tra hiển thị Reaction trên bình luận (XenForo ReactionsBar):")
    if reaction_examples:
        print(f"Tìm thấy {len(reaction_examples)} bình luận có reaction được hiển thị:")
        for rx in reaction_examples[:3]:
            print(f"  • Ảnh: {rx['image']}")
            print(f"    - Tác giả: {rx['author']}")
            print(f"    - Selector: {rx['selector']}")
            print(f"    - Nội dung reaction: {rx['text']}")
    else:
        print("  • Các ảnh được chọn chưa có reaction nào được gắn trên bình luận.")
        print("  • Selector chuẩn của XenForo 2.3 là: `article.message--comment .reactionsBar` hoặc `.reactionsBar.js-reactionsList`.")


def test_part_5_stability_10_requests(session: requests.Session):
    print("\n" + "=" * 80)
    print("MỤC 2.5: KIỂM TRA ĐỘ BỀN PHIÊN QUA 10 REQUEST LIÊN TIẾP (KHOẢNG NGHỈ >= 1.6s)")
    print("=" * 80)

    test_endpoints = [
        "https://fuexam.me/account/",
        "https://fuexam.me/threads/prm393-su26-fe-re.941/",
        "https://fuexam.me/media/prm393-su26-fe-re_001-webp.34522/",
        "https://fuexam.me/attachments/prm393-su26-fe-re_001-webp.68981/",
        "https://fuexam.me/account/preferences",
        "https://fuexam.me/forums/prm393.174/",
        "https://fuexam.me/threads/prm393-su26-fe-re.941/page-1",
        "https://fuexam.me/media/prm393-su26-fe-re_002-webp.34523/",
        "https://fuexam.me/account/security",
        "https://fuexam.me/account/",
    ]

    print(f"Thực hiện 10 request liên tiếp với khoảng dừng 1.6s để kiểm tra tính ổn định...")
    all_ok = True

    for i, url in enumerate(test_endpoints, 1):
        time.sleep(1.6)
        resp = session.get(url, allow_redirects=True, timeout=20)
        soup = BeautifulSoup(resp.text, "html.parser") if "text/html" in resp.headers.get("Content-Type", "") else None
        title = soup.title.string.strip() if soup and soup.title else "Non-HTML / Direct Data"
        data_logged_in = soup.find("html").get("data-logged-in") if soup and soup.find("html") else "N/A"

        status_ok = resp.status_code == 200 and "/login" not in resp.url
        if not status_ok:
            all_ok = False

        print(f"  Req {i:2d}/10 | HTTP {resp.status_code} | data-logged-in: {data_logged_in:<5} | URL: {resp.url[:45]:<45} | Tiêu đề: {title[:40]}")

    print(f"\nKết quả thử nghiệm 10 request: {'HOÀN HẢO (Phiên duy trì ổn định 100%, không bị Cloudflare hay XenForo chặn)' if all_ok else 'CÓ BẤT THƯỜNG'}")


def main():
    session, cookies_data = load_authenticated_session()
    soup_thread = test_part_1_and_2(session, cookies_data)
    test_part_3_attachment_download(session)
    test_part_4_comments_and_reactions(session, soup_thread)
    test_part_5_stability_10_requests(session)


if __name__ == "__main__":
    main()
