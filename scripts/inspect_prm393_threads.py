import re
import sys
from pathlib import Path
from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.modules.crawler.fuexam_crawler import get_authenticated_session

session = get_authenticated_session()
r = session.get("https://fuexam.me/forums/prm393.174/")
soup = BeautifulSoup(r.text, "html.parser")
for item in soup.select(".structItem--thread"):
    title_div = item.select_one(".structItem-title")
    if not title_div:
        continue
    label_el = title_div.select_one(".label")
    label_text = label_el.text.strip() if label_el else ""
    
    # The title link is the anchor having data-tp-primary or not having labelLink
    anchors = title_div.find_all("a")
    title_anchor = None
    for a in anchors:
        if "labelLink" not in a.get("class", []):
            title_anchor = a
            break
    
    title = title_anchor.text.strip() if title_anchor else "No Title"
    href = title_anchor.get("href", "") if title_anchor else ""
    # Clean /unread from href if present
    href = re.sub(r"/unread$", "/", href)
    
    # Also check post date
    date_el = item.select_one("time[datetime]")
    post_date = date_el.get("datetime") if date_el else ""
    
    print(f"[{label_text}] '{title}' -> {href} ({post_date})")
