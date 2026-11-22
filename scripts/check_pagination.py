import sys
from pathlib import Path
from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.modules.crawler.fuexam_crawler import get_authenticated_session

session = get_authenticated_session()
r = session.get("https://fuexam.me/media/prm393-su26-fe-re_001-webp.34522/")
soup = BeautifulSoup(r.text, "html.parser")

page_nav = soup.select(".pageNav, .pageNavSimple, .pageNav-page, a[href*='page-']")
print("Page nav found:", len(page_nav))
for p in page_nav:
    print(" ", p)

comments = soup.select(".message--comment")
print(f"Total comments on page: {len(comments)}")
for c in comments:
    user = c.select_one(".username")
    body = c.select_one(".bbWrapper")
    print("  User:", user.text.strip() if user else "", "->", body.text.strip() if body else "")
