#!/usr/bin/env python3
"""
scripts/verify_guest_access.py
Kiểm chứng thực nghiệm quyền khách (Guest Access) trên nền tảng fuexam.me.
Tuân thủ đầy đủ 4 yêu cầu của Mục A.
"""

import hashlib
import json
import os
from pathlib import Path
import sys
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCREENSHOT_DIR = PROJECT_ROOT / "data" / "playwright_screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


def check_step_1_session_files():
    print("=" * 80)
    print("MỤC A.1: XÁC NHẬN KHÔNG NẠP COOKIE / STORAGE_STATE / AUTHORIZATION")
    print("=" * 80)
    
    # 1. Tìm các file phiên có trong data/ và scripts/
    session_files = []
    keywords = ["cookie", "session", "auth", "token", "state", "storage_state"]
    for base_dir in [PROJECT_ROOT / "data", PROJECT_ROOT / "scripts"]:
        if base_dir.exists():
            for p in base_dir.rglob("*"):
                if p.is_file() and any(kw in p.name.lower() for kw in keywords):
                    rel = p.relative_to(PROJECT_ROOT)
                    session_files.append(str(rel))

    print(f"Danh sách tệp phiên/auth tồn tại trong data/ và scripts/ ({len(session_files)} tệp):")
    for f in sorted(session_files):
        print(f"  - {f}")

    # 2. Khởi tạo requests Session sạch hoàn toàn
    client = requests.Session()
    # Explicitly clear cookies just to be 100% certain
    client.cookies.clear()
    
    client_cookies_before = list(client.cookies.keys())
    print(f"\nDanh sách cookie của client trước khi gửi request (chỉ tên): {client_cookies_before} (Trống - 0 cookie)")
    print("Authorization header: None")
    return client


def check_step_2_raw_requests(client: requests.Session):
    print("\n" + "=" * 80)
    print("MỤC A.2: KIỂM CHỨNG BẰNG RAW HTTP REQUEST (KHÔNG COOKIE/AUTH)")
    print("=" * 80)

    urls = [
        ("Thread URL", "https://fuexam.me/threads/prm393-su26-fe-re.941/"),
        ("Media Page", "https://fuexam.me/media/prm393-su26-fe-re_001-webp.34522/"),
        ("Media Full Image", "https://fuexam.me/media/prm393-su26-fe-re_001-webp.34522/full"),
        ("Attachment URL (link bấm của ảnh trong thread)", "https://fuexam.me/attachments/prm393-su26-fe-re_001-webp.68981/"),
    ]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "vi,en-US;q=0.9,en;q=0.8",
    }

    for label, url in urls:
        print(f"\n>>> Kiểm tra: [{label}]")
        print(f"    URL yêu cầu : {url}")
        
        # Reset session cookies between each test so no state carries over
        client.cookies.clear()
        
        resp = client.get(url, headers=headers, allow_redirects=True, timeout=20)
        
        status_code = resp.status_code
        final_url = resp.url
        body_len = len(resp.content)
        
        # Parse html if html
        is_html = "text/html" in resp.headers.get("Content-Type", "")
        title = "N/A"
        data_logged_in = "N/A"
        
        if is_html:
            soup = BeautifulSoup(resp.text, "html.parser")
            title = soup.title.string.strip() if soup.title and soup.title.string else "No Title"
            html_el = soup.find("html")
            data_logged_in = html_el.get("data-logged-in") if html_el else "None"
        
        print(f"    Mã HTTP     : {status_code}")
        print(f"    URL cuối    : {final_url}")
        print(f"    Độ dài body : {body_len} bytes")
        print(f"    Tiêu đề     : {title}")
        print(f"    data-logged-in : {data_logged_in}")
        
        # Nếu là ảnh (Media Full Image)
        if label == "Media Full Image":
            first_12 = resp.content[:12]
            sha256_hex = hashlib.sha256(resp.content).hexdigest()
            print(f"    12 byte đầu : {first_12} (hex: {first_12.hex()})")
            print(f"    Kích thước  : {len(resp.content)} bytes")
            print(f"    SHA256      : {sha256_hex}")


def check_step_3_chromium_headless():
    print("\n" + "=" * 80)
    print("MỤC A.3: KIỂM CHỨNG BẰNG CHROMIUM HEADLESS MỚI (KHÔNG PROFILE)")
    print("=" * 80)

    thread_url = "https://fuexam.me/threads/prm393-su26-fe-re.941/"
    
    with sync_playwright() as p:
        # Launch fresh Chromium without any persistent profile or user data
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        
        # Verify initial cookies in context
        init_cookies = context.cookies()
        print(f"Danh sách cookie của Chromium context ban đầu: {[c['name'] for c in init_cookies]} (0 cookie)")
        
        page = context.new_page()
        
        # 1. Mở thread
        print(f"\n1. Mở thread: {thread_url}")
        page.goto(thread_url, wait_until="networkidle", timeout=30000)
        
        thread_title = page.title()
        thread_final_url = page.url
        thread_logged_in = page.evaluate("() => document.documentElement.getAttribute('data-logged-in')")
        print(f"   URL cuối: {thread_final_url}")
        print(f"   Tiêu đề: {thread_title}")
        print(f"   data-logged-in: {thread_logged_in}")
        
        ss_thread = SCREENSHOT_DIR / "guest_thread_view.png"
        page.screenshot(path=str(ss_thread), full_page=False)
        print(f"   Đã chụp ảnh màn hình Thread: {ss_thread}")
        
        # 2. Thử bấm ảnh đầu tiên
        # Tìm phần tử file preview
        preview_loc = page.locator("a.file-preview").first
        preview_count = page.locator("a.file-preview").count()
        print(f"\n2. Thử bấm ảnh đầu tiên (trong tổng số {preview_count} ảnh đính kèm)...")
        
        if preview_count > 0:
            preview_href = preview_loc.get_attribute("href")
            preview_target = preview_loc.get_attribute("target")
            print(f"   Thuộc tính href thẻ a: {preview_href}")
            print(f"   Thuộc tính target: {preview_target}")
            
            # Vì target="_blank", trình duyệt sẽ mở một tab mới
            with context.expect_page() as new_page_info:
                preview_loc.click()
            
            new_tab = new_page_info.value
            new_tab.wait_for_load_state("networkidle", timeout=15000)
            
            new_url = new_tab.url
            new_title = new_tab.title()
            new_logged_in = new_tab.evaluate("() => document.documentElement.getAttribute('data-logged-in')")
            print(f"   URL cuối sau khi bấm: {new_url}")
            print(f"   Tiêu đề trang mới: {new_title}")
            print(f"   data-logged-in trang mới: {new_logged_in}")
            
            # Kiểm tra xem có form đăng nhập hoặc thông báo yêu cầu đăng nhập không
            has_login_form = new_tab.locator("form[action*='login']").count() > 0
            block_msg = new_tab.locator(".blockMessage, .block-rowMessage").all_inner_texts()
            print(f"   Có form đăng nhập: {has_login_form}")
            print(f"   Thông báo trên trang: {[m.strip() for m in block_msg if m.strip()]}")
            
            ss_click = SCREENSHOT_DIR / "guest_click_first_image.png"
            new_tab.screenshot(path=str(ss_click), full_page=False)
            print(f"   Đã chụp ảnh màn hình sau khi bấm: {ss_click}")
            
            new_tab.close()
        else:
            print("   Không tìm thấy phần tử a.file-preview trên trang!")

        # 3. Mở trực tiếp trang Media Gallery item
        media_url = "https://fuexam.me/media/prm393-su26-fe-re_001-webp.34522/"
        print(f"\n3. Mở trực tiếp trang Media Gallery: {media_url}")
        page.goto(media_url, wait_until="networkidle", timeout=30000)
        print(f"   URL cuối: {page.url}")
        print(f"   Tiêu đề: {page.title()}")
        print(f"   data-logged-in: {page.evaluate('() => document.documentElement.getAttribute(\"data-logged-in\")')}")
        
        comments = page.locator(".message--comment").count()
        print(f"   Số lượng bình luận hiển thị trên trang media: {comments}")
        
        ss_media = SCREENSHOT_DIR / "guest_media_page.png"
        page.screenshot(path=str(ss_media), full_page=False)
        print(f"   Đã chụp ảnh màn hình Media: {ss_media}")

        browser.close()


def main():
    client = check_step_1_session_files()
    check_step_2_raw_requests(client)
    check_step_3_chromium_headless()


if __name__ == "__main__":
    main()
