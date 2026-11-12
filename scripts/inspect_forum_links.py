import re
from bs4 import BeautifulSoup

with open('backend/tests/fixtures/subjects_category_page.html', 'r', encoding='utf-8') as f:
    soup = BeautifulSoup(f.read(), 'html.parser')

links = soup.select('a[href*="/forums/"]')
print('Total links with /forums/:', len(links))
items = []
for a in links:
    href = a.get('href', '')
    text = a.get_text(strip=True)
    title = a.get('title', '')
    items.append((href, text, title))

print('First 30:')
for it in items[:30]:
    print(' ', it)

garbage = [it for it in items if it[1] == 'RSS' or it[0] == '/forums/-/' or '-' in it[0]]
print('\nGarbage candidates count:', len(garbage))
for g in garbage[:20]:
    print('  Garbage:', g)
