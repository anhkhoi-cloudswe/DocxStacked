import time
from playwright.sync_api import sync_playwright
from pathlib import Path
from bs4 import BeautifulSoup

profile_dir = Path("data/browser_profile").resolve()
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(user_data_dir=str(profile_dir), channel="chrome", headless=True)
    # Search forum for media with high comment count or older subjects
    # In XenForo Media Gallery, /media/ has top viewed or recently commented!
    resp = ctx.request.get("https://fuoverflow.com/media/")
    if resp.status == 200:
        soup = BeautifulSoup(resp.text(), "html.parser")
        items = soup.select(".xfmgMediaItem, a[href*='/media/']")
        print("Items on /media/:", len(items))
        for a in items[:15]:
            href = a.get("href")
            if href and "/media/" in href and href != "/media/":
                print(" ", href, a.get_text(strip=True)[:40])
                
    # Also check /whats-new/media-comments/
    resp_cmt = ctx.request.get("https://fuoverflow.com/whats-new/media-comments/")
    print("\nWhats new media comments status:", resp_cmt.status)
    if resp_cmt.status == 200:
        soup = BeautifulSoup(resp_cmt.text(), "html.parser")
        comment_items = soup.select(".message--comment, .contentRow, .structItem")
        print("Recent commented media count:", len(comment_items))
        for ci in comment_items[:10]:
            link = ci.select_one("a[href*='/media/']")
            print("  Commented media:", link.get("href") if link else None, ci.get_text(strip=True)[:60])
            
    ctx.close()

