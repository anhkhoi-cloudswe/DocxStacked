import json
import time
from playwright.sync_api import sync_playwright
from pathlib import Path
from bs4 import BeautifulSoup

BASE_DIR = Path.cwd()
fixtures_dir = BASE_DIR / "data" / "fixtures"
profile_dir = BASE_DIR / "data" / "browser_profile"

# Candidate media URLs
candidates = []
for fp in fixtures_dir.glob("sample_thread_fe_*.html"):
    content = fp.read_text(encoding="utf-8")
    soup = BeautifulSoup(content, "html.parser")
    for a in soup.select("li.file a.file-preview"):
        sidebar_href = a.get("data-lb-sidebar-href")
        if sidebar_href and "/media/" in sidebar_href:
            raw_href = sidebar_href.split("?")[0]
            url = f"https://fuoverflow.com{raw_href}"
            if url not in candidates:
                candidates.append(url)

print(f"Total candidates from CSD202 and PRN212: {len(candidates)}")

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir),
        channel="chrome",
        headless=True
    )
    
    # Scan candidates to find comment counts
    results = []
    print("Scanning candidates for comments, replies, reactions...")
    for idx, c_url in enumerate(candidates[:40]):
        try:
            resp = ctx.request.get(c_url, timeout=10000)
            if resp.status == 200:
                soup = BeautifulSoup(resp.text(), "html.parser")
                comments = soup.select(".message--mediaComment, .comment, article.message[data-content]")
                replies = soup.select(".comment--reply, .message--response, .commentList .comment .comment")
                reactions = soup.select(".reactionsBar, .reaction, .reactionsBar-linkTotal")
                if len(comments) > 0 or len(reactions) > 0:
                    results.append({
                        "url": c_url,
                        "comments": len(comments),
                        "replies": len(replies),
                        "reactions": len(reactions)
                    })
                    print(f"  [Found #{len(results)}] {c_url.split('/')[-2]}: {len(comments)} cmt, {len(replies)} reply, {len(reactions)} react")
                    if len(results) >= 8:
                        break
        except Exception as e:
            pass
            
    print(f"\nFound {len(results)} media items with comments/reactions.")
    ctx.close()

