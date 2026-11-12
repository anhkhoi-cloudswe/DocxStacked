from bs4 import BeautifulSoup
from backend.app.modules.crawler.browser import get_browser_manager

bm = get_browser_manager()
ctx = bm.start_context(headless=True)
url = "https://fuoverflow.com/media/q1-webp.134314/"
resp = ctx.request.get(url)
soup = BeautifulSoup(resp.text(), "html.parser")
print("Title:", soup.title.string if soup.title else "No title")
print("Logged in attr:", soup.html.get("data-logged-in") if soup.html else "No html")
# Check if comments container exists
print("Containers found:")
for sel in [".message--comment", ".message--mediaComment", ".js-comment", ".commentsList", ".message-responses", ".xfmgCommentList", ".block-body"]:
    print(f"  {sel}: {len(soup.select(sel))}")
bm.close()

