#!/usr/bin/env python3
"""
scripts/dev/collect_phase05_fixtures.py - Collect 5 real media fixtures
"""

import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

BASE_DIR = Path.cwd()
DATA_DIR = BASE_DIR / "data"
PROFILE_DIR = DATA_DIR / "browser_profile"
RAW_DIR = DATA_DIR / "fixtures" / "raw"
CLEAN_DIR = DATA_DIR / "fixtures" / "clean"
TEST_FIXTURES_DIR = BASE_DIR / "backend" / "tests" / "fixtures"

RAW_DIR.mkdir(parents=True, exist_ok=True)
CLEAN_DIR.mkdir(parents=True, exist_ok=True)
TEST_FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

TARGET_MEDIA = [
    "https://fuoverflow.com/media/q11-webp.137454/",  # 14 comments, VNR202
    "https://fuoverflow.com/media/q36-webp.130985/",  # 8 comments, SWD392
    "https://fuoverflow.com/media/q35-webp.130984/",  # 9 comments, SWD392
    "https://fuoverflow.com/media/q1-webp.134314/",   # 2 comments, CSD202
    "https://fuoverflow.com/media/q2-webp.134315/",   # 2 comments, CSD202
]

def sanitize_html(html_str: str) -> str:
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

def main():
    print("Collecting 5 real media fixtures...")
    collected = []
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",
            headless=True
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        for url in TARGET_MEDIA:
            print(f"\nProcessing: {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(2)
            
            slug = urlparse(url).path.strip("/").replace("/", "_").replace(".", "_")
            
            # 1. Full HTML & screenshot
            full_html = page.content()
            raw_html_path = RAW_DIR / f"{slug}_full.html"
            png_path = RAW_DIR / f"{slug}.png"
            raw_html_path.write_text(full_html, encoding="utf-8")
            page.screenshot(path=str(png_path), full_page=False)
            
            # 2. AJAX version
            ajax_url = f"{url}?lightbox=1"
            ajax_headers = {
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json, text/javascript, */*; q=0.01",
            }
            ajax_resp = ctx.request.get(ajax_url, headers=ajax_headers)
            raw_ajax_path = RAW_DIR / f"{slug}_ajax.html"
            raw_ajax_path.write_text(ajax_resp.text(), encoding="utf-8")
            
            # 3. Clean version
            clean_html = sanitize_html(full_html)
            clean_path = CLEAN_DIR / f"{slug}_clean.html"
            clean_path.write_text(clean_html, encoding="utf-8")
            
            test_fixture_path = TEST_FIXTURES_DIR / f"{slug}_clean.html"
            test_fixture_path.write_text(clean_html, encoding="utf-8")
            
            soup = BeautifulSoup(full_html, "html.parser")
            cmts = soup.select(".message--comment")
            
            info = {
                "url": url,
                "slug": slug,
                "title": soup.title.string if soup.title else "",
                "comments_count": len(cmts),
                "raw_html": str(raw_html_path.relative_to(BASE_DIR)),
                "raw_ajax": str(raw_ajax_path.relative_to(BASE_DIR)),
                "clean_html": str(clean_path.relative_to(BASE_DIR)),
                "test_fixture": str(test_fixture_path.relative_to(BASE_DIR)),
                "sample_comments": [c.select_one(".message-body").get_text(strip=True)[:50] for c in cmts[:3]]
            }
            collected.append(info)
            print(f"  Saved {slug} with {len(cmts)} comments!")
            
        summary_path = DATA_DIR / "phase05_capture_summary.json"
        summary_path.write_text(json.dumps(collected, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nAll 5 fixtures collected and summarized at {summary_path}")
        ctx.close()

if __name__ == "__main__":
    main()

