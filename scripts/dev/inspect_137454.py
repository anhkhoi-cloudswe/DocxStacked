from playwright.sync_api import sync_playwright
from pathlib import Path
from bs4 import BeautifulSoup

profile_dir = Path("data/browser_profile").resolve()
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(user_data_dir=str(profile_dir), channel="chrome", headless=True)
    resp = ctx.request.get("https://fuoverflow.com/media/137454/")
    soup = BeautifulSoup(resp.text(), "html.parser")
    print("Page Title:", soup.title.string)
    
    # Check comments structure
    cmts = soup.select(".message--comment")
    print(f"Total comments: {len(cmts)}")
    for i, c in enumerate(cmts[:5]):
        print(f"\n--- Comment {i+1} ---")
        author = c.select_one(".message-name, .comment-user, .username, .comment-author")
        body = c.select_one(".message-body, .comment-content, .bbWrapper")
        time_el = c.select_one("time[datetime], time")
        reactions_bar = c.select_one(".reactionsBar")
        print("  Author:", author.get_text(strip=True) if author else None)
        print("  Body:", body.get_text(strip=True) if body else None)
        print("  Time:", time_el.get_text(strip=True) if time_el else None, time_el.get("datetime") if time_el else None)
        if reactions_bar:
            print("  Reactions bar text:", reactions_bar.get_text(strip=True))
            # Links inside reactionsBar
            for rlink in reactions_bar.select(".reactionsBar-link, a"):
                print("    react link:", rlink.get("href"), rlink.get_text(strip=True))
                
        # Action bar (reaction button, reply button)
        action_bar = c.select(".actionBar-action")
        print("  Action bar:", [a.get_text(strip=True) for a in action_bar])
        for a in action_bar:
            if "reply" in a.get("class", []):
                print("    Reply button href:", a.get("href"))
                
    # Check pagination of comments
    page_nav = soup.select(".pageNav, .pageNav-jump, .pageNav-page")
    print("\nPage nav elements:", [p.get_text(strip=True) for p in page_nav])
    
    ctx.close()

