from pathlib import Path
from bs4 import BeautifulSoup

content = Path("data/fixtures/sample_thread_fe_csd202.html").read_text(encoding="utf-8")
soup = BeautifulSoup(content, "html.parser")

imgs = soup.find_all("img")
print(f"Total img tags: {len(imgs)}")

for idx, img in enumerate(imgs):
    src = img.get("src", "")
    if "attachments" in src:
        # Trace parents up
        parents = [p.name + ("." + ".".join(p.get("class", [])) if p.get("class") else "") for p in img.parents]
        print(f"\nAttachment Img #{idx}: {src[:80]}")
        print("  Parents hierarchy (bottom up):", " -> ".join(parents[:6]))
        break

# Let's inspect all attachment containers
att_divs = soup.find_all(class_=lambda c: c and any(k in c.lower() for k in ["attach", "file", "lbcontainer", "carousel", "slider"]))
print(f"\nAttachment-related divs count: {len(att_divs)}")
for ad in att_divs[:5]:
    print(f"  Class: {ad.get('class')}")
    print(f"  Sample HTML: {str(ad)[:150]}...")

