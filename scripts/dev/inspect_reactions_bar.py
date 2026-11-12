from playwright.sync_api import sync_playwright
from pathlib import Path
from bs4 import BeautifulSoup

profile_dir = Path("data/browser_profile").resolve()
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(user_data_dir=str(profile_dir), channel="chrome", headless=True)
    resp = ctx.request.get("https://fuoverflow.com/media/134314/")
    soup = BeautifulSoup(resp.text(), "html.parser")
    for i, c in enumerate(soup.select(".message--comment")):
        print(f"Comment {i+1}:")
        rb = c.select_one(".reactionsBar")
        if rb:
            print("  reactionsBar HTML:", rb.prettify())
        total = c.select_one(".reactionsBar-link, .reaction, .reactionsBar-linkTotal")
        if total:
            print("  reactions element:", total)
    ctx.close()

