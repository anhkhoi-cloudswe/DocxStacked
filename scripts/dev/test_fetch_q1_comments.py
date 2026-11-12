from pathlib import Path
from bs4 import BeautifulSoup
from backend.app.modules.crawler.browser import get_browser_manager

bm = get_browser_manager()
ctx = bm.start_context(headless=True)
url = "https://fuoverflow.com/media/q1-webp.134314/"
print(f"Testing fetch: {url}")
resp = ctx.request.get(url, timeout=15000)
print(f"Status: {resp.status}")
if resp.status == 200:
    soup = BeautifulSoup(resp.text(), "html.parser")
    cmts = soup.select(".message--comment, .message--mediaComment, .js-comment")
    print(f"Found {len(cmts)} comments!")
    for i, c in enumerate(cmts):
        body = c.select_one(".message-body .bbWrapper")
        body_text = body.get_text(" ", strip=True) if body else ""
        print(f"  [{i+1}] {body_text[:60]}")
bm.close_context()

