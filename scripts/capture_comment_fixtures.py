#!/usr/bin/env python3
"""
scripts/capture_comment_fixtures.py - Phase 0.5 Fixture Capturing Tool

Workflow:
1. Launch headed Google Chrome with persistent profile (data/browser_profile).
2. Wait for manual login (detects data-logged-in="true", user menu, cookie xf_user, or media probe status 200).
3. Scan/Capture 3-5 real /media/{slug}.{id}/ pages with comments, replies, reactions.
   - Saves regular HTML (full page).
   - Saves AJAX response (X-Requested-With: XMLHttpRequest).
   - Saves AJAX HTML fragment if response is JSON.
   - Takes screenshot (.png).
   - Tests direct CDN image download (with and without cookies).
4. Cleans/Sanitizes the fixtures (removing tokens, user names, avatars).
5. Copies sanitized fixtures to backend/tests/fixtures/ for testing.
"""

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

# Ensure immediate unbuffered output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
PROFILE_DIR = DATA_DIR / "browser_profile"
RAW_DIR = DATA_DIR / "fixtures" / "raw"
CLEAN_DIR = DATA_DIR / "fixtures" / "clean"
TEST_FIXTURES_DIR = BASE_DIR / "backend" / "tests" / "fixtures"

RAW_DIR.mkdir(parents=True, exist_ok=True)
CLEAN_DIR.mkdir(parents=True, exist_ok=True)
TEST_FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://fuoverflow.com"
LOGIN_URL = "https://fuoverflow.com/login/"
PROBE_MEDIA_URL = "https://fuoverflow.com/media/q1-webp.134314/"

INJECTED_BANNER_SCRIPT = """
(function() {
  function createBanner() {
    if (document.getElementById('phase05-banner')) return;
    if (!document.body) {
      setTimeout(createBanner, 100);
      return;
    }
    const banner = document.createElement('div');
    banner.id = 'phase05-banner';
    banner.style.position = 'fixed';
    banner.style.bottom = '20px';
    banner.style.right = '20px';
    banner.style.zIndex = '2147483647';
    banner.style.backgroundColor = '#0f172a';
    banner.style.color = '#f8fafc';
    banner.style.padding = '14px 18px';
    banner.style.borderRadius = '10px';
    banner.style.border = '2px solid #3b82f6';
    banner.style.boxShadow = '0 10px 30px rgba(0,0,0,0.6)';
    banner.style.fontFamily = 'system-ui, -apple-system, sans-serif';
    banner.style.fontSize = '13px';
    banner.style.maxWidth = '380px';
    banner.style.display = 'flex';
    banner.style.flexDirection = 'column';
    banner.style.gap = '8px';

    const header = document.createElement('div');
    header.style.display = 'flex';
    header.style.justifyContent = 'space-between';
    header.style.alignItems = 'center';
    header.innerHTML = '<b style="color:#60a5fa; font-size:14px">⚡ Gomde Phase 0.5</b> <span id="p05-status" style="color:#fbbf24; font-size:11px; font-weight:bold">Chờ đăng nhập...</span>';
    banner.appendChild(header);

    const desc = document.createElement('div');
    desc.id = 'p05-desc';
    desc.textContent = '1. Hãy đăng nhập bằng Google hoặc tài khoản trên trang này.\\n2. Sau khi xong, bấm nút xanh bên dưới.';
    desc.style.color = '#cbd5e1';
    desc.style.fontSize = '12px';
    desc.style.lineHeight = '1.4';
    banner.appendChild(desc);

    const btnGroup = document.createElement('div');
    btnGroup.style.display = 'flex';
    btnGroup.style.flexWrap = 'wrap';
    btnGroup.style.gap = '8px';
    btnGroup.style.marginTop = '6px';

    const loggedBtn = document.createElement('button');
    loggedBtn.id = 'p05-logged-btn';
    loggedBtn.textContent = '👉 Tôi đã đăng nhập xong';
    loggedBtn.style.padding = '8px 12px';
    loggedBtn.style.backgroundColor = '#16a34a';
    loggedBtn.style.color = '#fff';
    loggedBtn.style.border = 'none';
    loggedBtn.style.borderRadius = '6px';
    loggedBtn.style.cursor = 'pointer';
    loggedBtn.style.fontWeight = 'bold';
    loggedBtn.style.fontSize = '12px';
    loggedBtn.onclick = async () => {
      loggedBtn.disabled = true;
      loggedBtn.textContent = 'Đang kiểm tra...';
      if (window.confirmLoginBinding) {
        const res = await window.confirmLoginBinding();
        document.getElementById('p05-desc').textContent = res;
      }
      setTimeout(() => {
        loggedBtn.disabled = false;
        loggedBtn.textContent = '👉 Tôi đã đăng nhập xong';
      }, 2000);
    };

    const saveBtn = document.createElement('button');
    saveBtn.id = 'p05-save-btn';
    saveBtn.textContent = '📸 Lưu trang Media này';
    saveBtn.style.padding = '8px 12px';
    saveBtn.style.backgroundColor = '#2563eb';
    saveBtn.style.color = '#fff';
    saveBtn.style.border = 'none';
    saveBtn.style.borderRadius = '6px';
    saveBtn.style.cursor = 'pointer';
    saveBtn.style.fontWeight = 'bold';
    saveBtn.style.fontSize = '12px';
    saveBtn.onclick = async () => {
      saveBtn.disabled = true;
      saveBtn.textContent = '⏳ Đang lưu...';
      try {
        if (window.captureCurrentMediaBinding) {
          const res = await window.captureCurrentMediaBinding();
          document.getElementById('p05-desc').textContent = res;
        }
      } catch (e) {
        document.getElementById('p05-desc').textContent = 'Lỗi: ' + e.message;
      }
      setTimeout(() => {
        saveBtn.disabled = false;
        saveBtn.textContent = '📸 Lưu trang Media này';
      }, 2000);
    };

    btnGroup.appendChild(loggedBtn);
    btnGroup.appendChild(saveBtn);
    banner.appendChild(btnGroup);

    document.body.appendChild(banner);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', createBanner);
  } else {
    createBanner();
  }
})();
"""


def check_is_logged_in(context) -> bool:
    """Check if current session is logged into FUOverflow."""
    try:
        # 1. Check cookies across all domains
        for c in context.cookies():
            if c.get("name") in ("xf_user", "xf_user_session") and c.get("value"):
                return True

        # 2. Check DOM across all open pages
        for p in context.pages:
            try:
                if not p.is_closed() and "fuoverflow.com" in p.url:
                    content = p.content()
                    if 'data-logged-in="true"' in content:
                        return True
                    if p.query_selector(".p-navgroup-link--user, .p-account .avatar, a[href*='/account/preferences']"):
                        return True
            except Exception:
                pass

        # 3. Direct probe on media url (status 200 means logged in, 403 means guest)
        resp = context.request.get(PROBE_MEDIA_URL)
        if resp.status == 200:
            return True
    except Exception:
        pass
    return False


def sanitize_html(html_str: str) -> str:
    """Sanitize HTML fixture: remove tokens, session IDs, sensitive personal names."""
    soup = BeautifulSoup(html_str, "html.parser")

    # 1. Remove CSRF and session tokens in form inputs
    for el in soup.find_all(attrs={"name": "_xfToken"}):
        el["value"] = "[SANITIZED_CSRF_TOKEN]"
    for el in soup.find_all(attrs={"data-csrf": True}):
        el["data-csrf"] = "[SANITIZED_CSRF_TOKEN]"
    for el in soup.find_all(attrs={"data-xf-init": True}):
        if "csrf" in el.get("data-xf-init", ""):
            el["data-xf-init"] = el["data-xf-init"].replace("csrf", "sanitized-csrf")

    # 2. Remove user email / sensitive username in account links
    user_menu = soup.select_one(".p-navgroup-link--user")
    if user_menu:
        for span in user_menu.find_all("span"):
            span.string = "TestUser"

    # 3. Anonymize comment authors slightly while keeping structure intact
    authors = soup.select(".message-name, .comment-user, .username, .comment-author")
    for i, a in enumerate(authors):
        tag_name = chr(65 + (i % 26)) + (str(i // 26) if i >= 26 else "")
        a.string = f"Student_{tag_name}"

    # 4. Anonymize avatars
    for av in soup.select("img.avatar, .avatar img"):
        av["src"] = "/attachments/avatar_sanitized.jpg"

    # 5. Sanitize inline script tokens
    for s in soup.find_all("script"):
        stext = s.string or ""
        if "_xfToken" in stext or "csrf" in stext or "visitor" in stext:
            stext = re.sub(r'"_xfToken":\s*"[^"]+"', '"_xfToken": "[SANITIZED]"', stext)
            stext = re.sub(r'"csrf":\s*"[^"]+"', '"csrf": "[SANITIZED]"', stext)
            stext = re.sub(r'"userId":\s*\d+', '"userId": 9999', stext)
            stext = re.sub(r'"userName":\s*"[^"]+"', '"userName": "Student_Test"', stext)
            s.string = stext

    # 6. Remove tracking scripts
    for s in soup.find_all("script"):
        src = s.get("src", "")
        if "googletagmanager" in src or "facebook" in src or "google-analytics" in src:
            s.decompose()

    return str(soup)


def extract_image_dimensions(data: bytes):
    import struct
    try:
        if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            chunk = data[12:16]
            if chunk == b'VP8 ':
                w = struct.unpack('<H', data[26:28])[0] & 0x3fff
                h = struct.unpack('<H', data[28:30])[0] & 0x3fff
                return f"{w}x{h} (Lossy WebP)"
            elif chunk == b'VP8L':
                b1, b2, b3, b4 = data[21:25]
                w = 1 + (((b2 & 0x3f) << 8) | b1)
                h = 1 + (((b4 & 0x0f) << 10) | (b3 << 2) | ((b2 & 0xc0) >> 6))
                return f"{w}x{h} (Lossless WebP)"
            elif chunk == b'VP8X':
                w = 1 + struct.unpack('<I', data[24:27] + b'\x00')[0]
                h = 1 + struct.unpack('<I', data[27:30] + b'\x00')[0]
                return f"{w}x{h} (Extended WebP)"
        elif data[:2] == b'\xff\xd8':
            return f"JPEG image ({len(data)} bytes)"
        elif data[:8] == b'\x89PNG\r\n\x1a\n':
            w, h = struct.unpack('>II', data[16:24])
            return f"{w}x{h} (PNG)"
    except Exception:
        pass
    return f"Image data ({len(data)} bytes)"


def test_cdn_image(image_url: str, cookies: dict) -> dict:
    """Test downloading CDN image directly with and without cookies."""
    import urllib.request
    import ssl
    ctx = ssl.create_default_context()
    headers_no_cookie = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    result = {
        "url": image_url,
        "direct_no_cookie": False,
        "direct_with_cookie": False,
        "status_no_cookie": None,
        "status_with_cookie": None,
        "content_type": None,
        "bytes_len": 0,
        "dimensions": None,
    }

    # 1. Test without cookies
    try:
        req = urllib.request.Request(image_url, headers=headers_no_cookie)
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            result["status_no_cookie"] = resp.status
            result["content_type"] = resp.headers.get("content-type")
            data = resp.read()
            result["bytes_len"] = len(data)
            if resp.status == 200 and len(data) > 0:
                result["direct_no_cookie"] = True
                result["dimensions"] = extract_image_dimensions(data)
    except Exception as e:
        result["status_no_cookie"] = str(e)

    # 2. Test with cookies if no_cookie failed
    if not result["direct_no_cookie"]:
        cookie_header = "; ".join([f"{k}={v}" for k, v in cookies.items()])
        headers_cookie = dict(headers_no_cookie)
        headers_cookie["Cookie"] = cookie_header
        try:
            req = urllib.request.Request(image_url, headers=headers_cookie)
            with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
                result["status_with_cookie"] = resp.status
                result["content_type"] = resp.headers.get("content-type")
                data = resp.read()
                result["bytes_len"] = len(data)
                if resp.status == 200 and len(data) > 0:
                    result["direct_with_cookie"] = True
                    result["dimensions"] = extract_image_dimensions(data)
        except Exception as e:
            result["status_with_cookie"] = str(e)

    return result


def capture_media_page(context, page, url: str) -> dict:
    """Capture full HTML, AJAX response, screenshot, and clean fixture for a media page."""
    print(f"\n[Capture] Đang tải trang media: {url}")
    parsed = urlparse(url)
    slug = parsed.path.strip("/").replace("/", "_").replace(".", "_")

    # 1. Full HTML & Screenshot
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    time.sleep(2)

    full_html = page.content()
    raw_html_path = RAW_DIR / f"{slug}_full.html"
    raw_png_path = RAW_DIR / f"{slug}.png"

    raw_html_path.write_text(full_html, encoding="utf-8")
    page.screenshot(path=str(raw_png_path), full_page=False)

    # 2. AJAX response with X-Requested-With: XMLHttpRequest
    ajax_url = url if "?lightbox=1" in url else f"{url}?lightbox=1"
    ajax_headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }
    ajax_resp = context.request.get(ajax_url, headers=ajax_headers)
    ajax_content = ajax_resp.text()

    raw_ajax_path = RAW_DIR / f"{slug}_ajax.txt"
    raw_ajax_path.write_text(ajax_content, encoding="utf-8")

    # If AJAX is JSON containing HTML fragment, also write the HTML fragment
    ajax_html_fragment = None
    try:
        ajax_json = json.loads(ajax_content)
        if isinstance(ajax_json, dict) and "html" in ajax_json:
            h = ajax_json["html"]
            if isinstance(h, dict) and "content" in h:
                ajax_html_fragment = h["content"]
            elif isinstance(h, str):
                ajax_html_fragment = h
            if ajax_html_fragment:
                fragment_path = RAW_DIR / f"{slug}_ajax_fragment.html"
                fragment_path.write_text(ajax_html_fragment, encoding="utf-8")
    except Exception:
        pass

    # 3. Analyze comments in the page
    soup = BeautifulSoup(full_html, "html.parser")

    # High-res image in media view
    media_img = soup.select_one(".xfmgMediaView-image img, .media-image img, .imageContainer img, section.message-attachments img")
    img_url = None
    if media_img:
        img_url = media_img.get("src") or media_img.get("data-url")
        if img_url and img_url.startswith("/"):
            img_url = urljoin(BASE_URL, img_url)

    # Cookies
    cookies = {c["name"]: c["value"] for c in context.cookies()}
    img_test_result = None
    if img_url:
        img_test_result = test_cdn_image(img_url, cookies)

    # Comments analysis
    comments = soup.select(".message--mediaComment, .comment, article.message[data-content], .commentList .comment")
    replies = soup.select(".comment--reply, .message--response, .commentList .comment .comment")
    reactions = soup.select(".reactionsBar, .reactionsBar-link, .reaction, .reactionsBar-linkTotal")

    comment_items = []
    for c in comments:
        author = c.select_one(".message-name, .comment-user, .username, .comment-author")
        body = c.select_one(".message-body, .comment-content, .bbWrapper")
        time_el = c.select_one("time[datetime], time, .u-dt")
        react_el = c.select_one(".reactionsBar, .reaction, .reactionsBar-linkTotal")

        comment_items.append({
            "author": author.get_text(strip=True) if author else "Unknown",
            "body": body.get_text(strip=True)[:100] if body else "",
            "time": time_el.get_text(strip=True) if time_el else "",
            "reactions": react_el.get_text(strip=True) if react_el else "0",
        })

    # 4. Clean and sanitize fixture for testing
    clean_html = sanitize_html(full_html)
    clean_path = CLEAN_DIR / f"{slug}_clean.html"
    clean_path.write_text(clean_html, encoding="utf-8")

    # Copy clean fixture to backend/tests/fixtures/
    test_fixture_path = TEST_FIXTURES_DIR / f"{slug}_clean.html"
    test_fixture_path.write_text(clean_html, encoding="utf-8")

    summary = {
        "url": url,
        "slug": slug,
        "raw_full_html": str(raw_html_path.relative_to(BASE_DIR)),
        "raw_ajax": str(raw_ajax_path.relative_to(BASE_DIR)),
        "screenshot": str(raw_png_path.relative_to(BASE_DIR)),
        "clean_html": str(clean_path.relative_to(BASE_DIR)),
        "test_fixture": str(test_fixture_path.relative_to(BASE_DIR)),
        "comments_count": len(comments),
        "replies_count": len(replies),
        "reactions_count": len(reactions),
        "sample_comments": comment_items[:3],
        "image_test": img_test_result,
    }

    print(f"  -> Đã lưu: {slug}")
    print(f"     Bình luận: {len(comments)} | Replies: {len(replies)} | Reactions: {len(reactions)}")
    if img_test_result:
        print(f"     Tải ảnh CDN: không cookie={img_test_result['direct_no_cookie']}, có cookie={img_test_result['direct_with_cookie']} ({img_test_result['dimensions']})")

    return summary


def find_candidate_media_urls() -> list:
    """Extract candidate media URLs from existing thread fixtures."""
    urls = []
    fixtures_dir = DATA_DIR / "fixtures"
    for fp in fixtures_dir.glob("sample_thread_fe_*.html"):
        content = fp.read_text(encoding="utf-8")
        soup = BeautifulSoup(content, "html.parser")
        for a in soup.select("li.file a.file-preview"):
            sidebar_href = a.get("data-lb-sidebar-href")
            if sidebar_href and "/media/" in sidebar_href:
                raw_href = sidebar_href.split("?")[0]
                full_url = urljoin(BASE_URL, raw_href)
                if full_url not in urls:
                    urls.append(full_url)
    return urls


def main():
    print("=" * 70)
    print("  Gomde Phase 0.5 — Persistent Login & Comment Fixture Collector")
    print("=" * 70)
    print(f"Thư mục Profile:  {PROFILE_DIR}")
    print(f"URL đích:         {BASE_URL}")
    print("-" * 70)

    manual_logged_in = [False]
    captured_fixtures = []

    with sync_playwright() as p:
        print("\n[Step 1/3] Khởi chạy Google Chrome (headed mode, profile persistent)...")
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",
            headless=False,
            viewport={"width": 1366, "height": 850},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
            ],
            no_viewport=True,
        )

        page = context.pages[0] if context.pages else context.new_page()

        # Expose bindings
        def on_confirm_login(source):
            if check_is_logged_in(context):
                manual_logged_in[0] = True
                print("\n[UI Notice] Người dùng bấm xác nhận đã đăng nhập thành công!")
                return "✅ Đã xác nhận đăng nhập thành công! Bắt đầu quét & lưu fixtures..."
            else:
                print("\n[UI Notice] Người dùng bấm nút nhưng media probe vẫn trả về 403.")
                return "⚠️ Chưa phát hiện đăng nhập! Vui lòng đăng nhập trên trang trước khi bấm."

        def on_capture_current(source):
            src_page = source["page"]
            curr_url = src_page.url
            if "/media/" not in curr_url:
                return f"Vui lòng vào trang /media/... trước khi lưu! (URL hiện tại: {curr_url})"
            res = capture_media_page(context, src_page, curr_url)
            captured_fixtures.append(res)
            return f"Đã lưu: {res['slug']} ({res['comments_count']} cmt, {res['replies_count']} replies)!"

        context.expose_binding("confirmLoginBinding", on_confirm_login)
        context.expose_binding("captureCurrentMediaBinding", on_capture_current)
        context.add_init_script(INJECTED_BANNER_SCRIPT)

        # Check login
        print(f"[Step 2/3] Mở trang đăng nhập {LOGIN_URL}...")
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=45000)
        time.sleep(2)

        logged_in = check_is_logged_in(context)
        if not logged_in:
            print("\n" + "=" * 65)
            print(">>> CHỜ BẠN ĐĂNG NHẬP THỦ CÔNG TRÊN TRÌNH DUYỆT CHROME <<<")
            print("1. Hãy đăng nhập bằng Google OAuth (@fpt.edu.vn) hoặc tài khoản.")
            print("2. Sau khi đăng nhập, script sẽ tự nhận diện hoặc bạn có thể bấm:")
            print("   '👉 Tôi đã đăng nhập xong' trên banner góc phải màn hình.")
            print("=" * 65 + "\n")

            wait_count = 0
            while not manual_logged_in[0]:
                time.sleep(2)
                wait_count += 1
                if check_is_logged_in(context):
                    print("\n🎉 ĐĂNG NHẬP THÀNH CÔNG! Phiên đăng nhập đã được ghi nhận.")
                    logged_in = True
                    break
                if wait_count % 15 == 0:
                    print(f"[Đang chờ bạn đăng nhập... đã đợi {wait_count * 2} giây]")

        print("\n[Step 3/3] Bắt đầu quét & thu thập 3-5 trang /media/... THẬT...")
        try:
            page.evaluate("""() => {
                const status = document.getElementById('p05-status');
                if (status) { status.textContent = '✅ Đã đăng nhập!'; status.style.color = '#4ade80'; }
                const desc = document.getElementById('p05-desc');
                if (desc) desc.textContent = 'Đang tự động quét & lưu các trang media có nhiều bình luận...';
            }""")
        except Exception:
            pass

        candidates = find_candidate_media_urls()
        print(f"Danh sách {len(candidates)} candidate media URLs từ các đề thi đã khảo sát.")

        # Scan candidates to find pages with comments, replies, reactions
        rich_candidates = []
        print("\nĐang kiểm tra nhanh các trang candidate để tìm câu có thảo luận/upvote...")
        for idx, c_url in enumerate(candidates):
            if len(rich_candidates) >= 5:
                break
            try:
                resp = context.request.get(c_url, timeout=10000)
                if resp.status == 200:
                    text = resp.text()
                    soup = BeautifulSoup(text, "html.parser")
                    comments = soup.select(".message--mediaComment, .comment, article.message[data-content]")
                    reactions = soup.select(".reactionsBar, .reaction")
                    print(f"  [{idx+1}/{len(candidates)}] {c_url.split('/')[-2]}: {len(comments)} bình luận, {len(reactions)} reaction")
                    if len(comments) >= 1 or len(reactions) >= 1:
                        rich_candidates.append(c_url)
            except Exception as e:
                pass

        # Fallback if few candidates had comments in first scan
        if len(rich_candidates) < 3 and candidates:
            for c in candidates:
                if c not in rich_candidates:
                    rich_candidates.append(c)
                if len(rich_candidates) >= 4:
                    break

        print(f"\nTiến hành tải và chụp {len(rich_candidates)} trang thảo luận...")
        for c_url in rich_candidates:
            if len(captured_fixtures) >= 5:
                break
            try:
                res = capture_media_page(context, page, c_url)
                captured_fixtures.append(res)
                time.sleep(1.5)
            except Exception as e:
                print(f"Lỗi khi lưu {c_url}: {e}")

        print(f"\n========================================================")
        print(f"Đã lưu thành công {len(captured_fixtures)} fixtures!")
        for f in captured_fixtures:
            print(f"  - {f['slug']}: {f['comments_count']} comments, {f['replies_count']} replies, {f['reactions_count']} reactions")
        print(f"========================================================")

        summary_path = DATA_DIR / "phase05_capture_summary.json"
        summary_path.write_text(json.dumps(captured_fixtures, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Summary JSON đã ghi tại: {summary_path.relative_to(BASE_DIR)}")

        # Update banner to inform user
        try:
            page.evaluate(f"""() => {{
                const status = document.getElementById('p05-status');
                if (status) {{ status.textContent = '🎉 Đã thu thập đủ {len(captured_fixtures)} fixtures!'; status.style.color = '#4ade80'; }}
                const desc = document.getElementById('p05-desc');
                if (desc) desc.textContent = 'Đã lưu xong 3-5 trang media thật (HTML, AJAX, ảnh, clean fixture). Trình duyệt sẽ đóng sau vài giây.';
            }}""")
        except Exception:
            pass
        time.sleep(3)

        context.close()
        print("\nĐã đóng trình duyệt Chrome. Hoàn tất thu thập fixtures!")


if __name__ == "__main__":
    main()
