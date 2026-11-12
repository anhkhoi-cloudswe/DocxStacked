import time
from playwright.sync_api import sync_playwright
from pathlib import Path
from bs4 import BeautifulSoup

profile_dir = Path("data/browser_profile").resolve()
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(user_data_dir=str(profile_dir), channel="chrome", headless=True)
    # Check SWD392 media
    for mid in [130985, 130984, 130983, 130982, 130980, 137454]:
        resp = ctx.request.get(f"https://fuoverflow.com/media/{mid}/")
        if resp.status == 200:
            soup = BeautifulSoup(resp.text(), "html.parser")
            cmts = soup.select(".message--comment")
            # check bbCodeBlock--quote or quotes
            quotes = soup.select(".bbCodeBlock--quote, blockquote")
            reacts = soup.select(".reactionsBar, .reaction")
            print(f"Media {mid} -> cmts: {len(cmts)}, quotes/replies: {len(quotes)}, reacts: {len(reacts)}")
            for c in cmts[:2]:
                print("   cmt:", c.select_one(".message-body").get_text(strip=True)[:60])
    ctx.close()

