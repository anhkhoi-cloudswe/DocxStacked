from playwright.sync_api import sync_playwright
from pathlib import Path
from bs4 import BeautifulSoup

profile_dir = Path("data/browser_profile").resolve()
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(user_data_dir=str(profile_dir), channel="chrome", headless=True)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto("https://fuoverflow.com/media/q1-webp.134314/", wait_until="domcontentloaded")
    soup = BeautifulSoup(page.content(), "html.parser")
    
    print("All img tags in media page:")
    for img in soup.find_all("img"):
        print(" ", img.get("src"), "| class:", img.get("class"), "| data-url:", img.get("data-url"))
        
    print("\nCheck attachment/media links:")
    for a in soup.select("a[href*='attachments'], a[href*='media']"):
        print(" ", a.get("href"), "| class:", a.get("class"))
        
    ctx.close()

