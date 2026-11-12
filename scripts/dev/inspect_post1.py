from pathlib import Path
from bs4 import BeautifulSoup

content = Path("data/fixtures/sample_thread_fe_csd202.html").read_text(encoding="utf-8")
soup = BeautifulSoup(content, "html.parser")

post1 = soup.find("article", id="js-post-17027")
if post1:
    print("Found post1!")
    # Find all divs with class
    for div in post1.find_all("div", recursive=False):
        print("Child div:", div.get("class"))
    
    # Search for bbWrapper (standard XenForo post content wrapper)
    bb = post1.find(class_=lambda c: c and "bbWrapper" in c)
    if bb:
        print("\n--- bbWrapper content ---")
        # List all direct children or tags
        children = [t.name for t in bb.find_all(recursive=False)]
        print(f"bbWrapper children tags: {children[:30]} (total: {len(children)})")
        
        # Check text and images
        imgs = bb.find_all("img")
        print(f"Images in bbWrapper: {len(imgs)}")
        for idx, img in enumerate(imgs[:10]):
            print(f"  Img #{idx+1}: src={img.get('src')}")
            # Check if there is text before/after image
            parent = img.parent
            prev_sib = img.previous_sibling
            next_sib = img.next_sibling
            print(f"    Parent tag: {parent.name} {parent.get('class')}")
            if prev_sib:
                print(f"    Prev text: {str(prev_sib).strip()[:50]}")
            if next_sib:
                print(f"    Next text: {str(next_sib).strip()[:50]}")
    else:
        print("No bbWrapper found in post1")

