from playwright.sync_api import sync_playwright
from pathlib import Path
from bs4 import BeautifulSoup

profile_dir = Path("data/browser_profile").resolve()
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(user_data_dir=str(profile_dir), channel="chrome", headless=True)
    
    # Check subjects with many comments: CSD202, PRN212, DBI202, MAS291...
    for mid in [134314, 134315, 134316, 134317, 134320, 140517, 140518, 140519, 140525, 140530]:
        url = f"https://fuoverflow.com/media/q-{mid}.{mid}/" # test slug-tolerant or direct
        resp = ctx.request.get(f"https://fuoverflow.com/media/{mid}/")
        if resp.status == 200:
            soup = BeautifulSoup(resp.text(), "html.parser")
            cmts = soup.select(".message--comment")
            # check reactions
            reacts = soup.select(".reactionsBar, .reaction")
            # check if reply button exists
            replies = soup.select("a[href*='comment?quote=']")
            print(f"Media {mid} -> status {resp.status}, title: {soup.title.string[:30] if soup.title else ''}, cmts: {len(cmts)}, reacts: {len(reacts)}, quote/reply buttons: {len(replies)}")
    ctx.close()

