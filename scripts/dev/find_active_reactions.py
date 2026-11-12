from playwright.sync_api import sync_playwright
from pathlib import Path
from bs4 import BeautifulSoup
import re

profile_dir = Path("data/browser_profile").resolve()
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(user_data_dir=str(profile_dir), channel="chrome", headless=True)
    # Search for comments that have actual likes/reactions
    print("Searching for media comments with reactions/upvotes...")
    for mid in range(134310, 134370):
        resp = ctx.request.get(f"https://fuoverflow.com/media/{mid}/")
        if resp.status == 200 and "reactionsBar js-reactionsList is-active" in resp.text():
            print(f"Found active reactions on media {mid}!")
            soup = BeautifulSoup(resp.text(), "html.parser")
            for c in soup.select(".message--comment"):
                active_rb = c.select_one(".reactionsBar.is-active, .js-reactionsList.is-active")
                if active_rb:
                    print("  Comment author:", c.select_one(".username").get_text(strip=True))
                    print("  Reaction text:", active_rb.get_text(strip=True))
                    print("  Reaction HTML:", active_rb)
            break
            
    # Also check quotes / replies
    print("\nSearching for comments with quotes / bbCodeBlock--quote...")
    for mid in [130985, 130984, 130983, 130980, 137454, 134314, 134315]:
        resp = ctx.request.get(f"https://fuoverflow.com/media/{mid}/")
        if "bbCodeBlock--quote" in resp.text():
            print(f"Found quote on media {mid}!")
    ctx.close()

