from playwright.sync_api import sync_playwright
from pathlib import Path
from bs4 import BeautifulSoup

profile_dir = Path("data/browser_profile").resolve()
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(user_data_dir=str(profile_dir), channel="chrome", headless=True)
    resp = ctx.request.get("https://fuoverflow.com/")
    soup = BeautifulSoup(resp.text(), "html.parser")
    # find threads with reaction score
    for item in soup.select(".structItem"):
        pairs = item.select(".pairs--justified")
        for pair in pairs:
            if "Phản ứng" in pair.get_text() or "Reaction" in pair.get_text() or "Thích" in pair.get_text():
                print(item.select_one(".structItem-title").get_text(strip=True), "->", pair.get_text(strip=True))
    ctx.close()

