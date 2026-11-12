from playwright.sync_api import sync_playwright
from pathlib import Path
from bs4 import BeautifulSoup

url = "https://fuoverflow.com/media/q1-webp.140517/?lightbox=1"
print(f"Loading media URL with Playwright: {url}")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    page = context.new_page()
    res = page.goto(url, wait_until="domcontentloaded", timeout=30000)
    print(f"Status: {res.status if res else 'None'}")
    print(f"Page title: {page.title()}")
    
    html = page.content()
    Path("data/fixtures/sample_media_lightbox_q1.html").write_text(html, encoding="utf-8")
    page.screenshot(path="data/fixtures/sample_media_lightbox_q1.png")
    print("Saved fixture to data/fixtures/sample_media_lightbox_q1.html and .png")
    
    soup = BeautifulSoup(html, "html.parser")
    # Check for comments / messages / bbWrapper
    comments = soup.select(".message--mediaComment, .comment, .message, .xfmgComment")
    print(f"Comments count: {len(comments)}")
    for c in comments:
        print(f"  Comment text: {c.get_text(strip=True)[:150]}")
        
    # Check if login required
    if "Đăng nhập" in html and 'data-logged-in="false"' in html:
        print("Logged in: False")
        
    browser.close()

