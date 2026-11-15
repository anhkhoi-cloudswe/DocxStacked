import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.modules.crawler.browser import get_browser_manager

bm = get_browser_manager()
page = bm.get_page()
try:
    resp = page.goto("https://fuoverflow.com/", wait_until="domcontentloaded", timeout=15000)
    print("HTTP Status:", resp.status if resp else None)
    content = page.content()
    logged_in = 'data-logged-in="true"' in content
    print("Logged in:", logged_in)
finally:
    bm.close()
