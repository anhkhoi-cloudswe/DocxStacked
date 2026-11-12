from playwright.sync_api import sync_playwright
from pathlib import Path
from bs4 import BeautifulSoup

profile_dir = Path("data/browser_profile").resolve()
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(user_data_dir=str(profile_dir), channel="chrome", headless=True)
    resp = ctx.request.get("https://fuoverflow.com/threads/csd202-su26-fe.7086/")
    soup = BeautifulSoup(resp.text(), "html.parser")
    first_post = soup.select_one("article.message")
    rb = first_post.select_one(".reactionsBar")
    if rb:
        print("Thread post reactionsBar:")
        print(rb.prettify())
    ctx.close()

