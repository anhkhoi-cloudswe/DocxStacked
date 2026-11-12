from pathlib import Path
from bs4 import BeautifulSoup

content = Path("data/fixtures/sample_thread_fe_csd202.html").read_text(encoding="utf-8")
soup = BeautifulSoup(content, "html.parser")

files = soup.select("ul.attachmentList li.file")
print(f"Total li.file found: {len(files)}")

if files:
    f1 = files[0]
    print("\n--- File #1 HTML ---")
    print(f1.prettify())

