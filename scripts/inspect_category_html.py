import os, sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from backend.app.modules.crawler.subjects import _fetch_url_sync, BeautifulSoup
html = _fetch_url_sync('https://fuoverflow.com/categories/subjects/')
print('Fetched HTML length:', len(html))
soup = BeautifulSoup(html, 'html.parser')
links = soup.select('.subNodeLink--forum, a[href*="/forums/"]')
print('Total forum links on category page:', len(links))
for a in links[:25]:
    href = a.get('href', '')
    text = a.get_text(strip=True)
    title = a.get('title', '')
    p_text = a.parent.get_text(strip=True) if a.parent else ''
    print(f'HREF: {href} | TEXT: {text} | TITLE: {title} | PARENT: {p_text}')
