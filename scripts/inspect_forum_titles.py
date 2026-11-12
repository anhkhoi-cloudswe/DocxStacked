import os, sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from backend.app.modules.crawler.subjects import _fetch_url_sync, BeautifulSoup

for code in ['CSD202', 'PRN232', 'AIH301', 'PRM393', 'ACC101']:
    url = f'https://fuoverflow.com/forums/{code}/'
    html = _fetch_url_sync(url)
    soup = BeautifulSoup(html, 'html.parser')
    h1 = soup.select_one('.p-title-value')
    h1_text = h1.get_text(strip=True) if h1 else ''
    title = soup.select_one('title')
    title_text = title.get_text(strip=True) if title else ''
    desc = soup.select_one('.p-description')
    desc_text = desc.get_text(strip=True) if desc else ''
    print(f'=== {code} ===')
    print('H1:', h1_text)
    print('Title:', title_text)
    print('Desc:', desc_text)
