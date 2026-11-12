from playwright.sync_api import sync_playwright
from pathlib import Path
from bs4 import BeautifulSoup
import json

profile_dir = Path("data/browser_profile").resolve()
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(user_data_dir=str(profile_dir), channel="chrome", headless=True)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://fuoverflow.com/media/q1-webp.134314/", wait_until="domcontentloaded")
    html = page.content()
    soup = BeautifulSoup(html, "html.parser")
    
    print("Page Title:", soup.title.string if soup.title else "")
    
    # 1. Image
    media_img = soup.select_one(".xfmgMediaView-image img, .media-image img, .imageContainer img, section.message-attachments img, .message-body img")
    print("Media Image:", media_img.get("src") if media_img else None)
    
    # 2. Comments container
    print("\nContainers:")
    for sel in [".message-responses", ".xfmgCommentList", ".block-body", ".commentList", ".commentsList", ".message"]:
        els = soup.select(sel)
        if els:
            print(f"  {sel}: {len(els)} elements")
            
    # 3. Individual comments
    comments = soup.select(".message--mediaComment, .comment, article.message[data-content]")
    print(f"\nComments count: {len(comments)}")
    for i, c in enumerate(comments):
        print(f"\n--- Comment {i+1} ---")
        print("  Classes:", c.get("class"))
        author = c.select_one(".message-name, .comment-user, .username, .comment-author")
        print("  Author:", author.get_text(strip=True) if author else None)
        body = c.select_one(".message-body, .comment-content, .bbWrapper")
        print("  Body:", body.get_text(strip=True) if body else None)
        time_el = c.select_one("time[datetime], time, .u-dt")
        print("  Time:", time_el.get_text(strip=True) if time_el else None, time_el.get("datetime") if time_el else None)
        reactions = c.select(".reactionsBar, .reactionsBar-link, .reaction, .reactionsBar-linkTotal")
        print("  Reactions:", [r.get_text(strip=True) for r in reactions])
        # Check replies
        replies = c.select(".comment--reply, .message--response, .commentList .comment")
        print("  Replies in comment:", len(replies))
        
    # Check pagination / load more
    load_more = soup.select(".pageNav, .pageNav-jump, .js-loadMore, a[href*='page=']")
    print("\nPagination / Load more:", [l.get_text(strip=True) for l in load_more])

    # 4. Check AJAX response
    ajax_url = "https://fuoverflow.com/media/q1-webp.134314/?lightbox=1"
    ajax_resp = ctx.request.get(ajax_url, headers={"X-Requested-With": "XMLHttpRequest"})
    print("\nAJAX Status:", ajax_resp.status)
    print("AJAX Content-Type:", ajax_resp.headers.get("content-type"))
    print("AJAX Body Sample:", ajax_resp.text()[:250])
    
    ctx.close()

