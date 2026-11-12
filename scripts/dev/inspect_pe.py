from pathlib import Path
from bs4 import BeautifulSoup

content = Path("data/fixtures/sample_thread_pe_csd202.html").read_text(encoding="utf-8")
soup = BeautifulSoup(content, "html.parser")

print("PE Thread Title:", soup.title.string if soup.title else "")

files = soup.select("ul.attachmentList li.file")
print(f"Total li.file found: {len(files)}")
for f in files:
    name = f.select_one(".file-name")
    img = f.select_one("img")
    print(f"  PE attachment: {name.get_text(strip=True) if name else 'no-name'} | img={img.get('src') if img else 'no-img'}")

# Check post content if images are in bbWrapper instead
bb = soup.select_one(".message-body .bbWrapper")
if bb:
    imgs = bb.find_all("img")
    print(f"Images in message body bbWrapper: {len(imgs)}")
    for im in imgs:
        print(f"  bbWrapper img: {im.get('src')}")

