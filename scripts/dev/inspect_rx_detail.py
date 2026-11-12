from pathlib import Path
from bs4 import BeautifulSoup

soup = BeautifulSoup(Path('data/fixtures/clean/media_q11-webp_137454_clean.html').read_text(encoding='utf-8'), 'html.parser')
for i, c in enumerate(soup.select('.message--comment')):
    rx = c.select_one('.reactionsBar')
    if rx:
        print(f"--- Comment {i+1} reactionsBar ---")
        print(rx.prettify())

