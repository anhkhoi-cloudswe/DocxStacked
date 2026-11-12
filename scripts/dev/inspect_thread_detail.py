import re
from pathlib import Path
from bs4 import BeautifulSoup

content = Path("data/fixtures/sample_thread_fe_csd202.html").read_text(encoding="utf-8")
soup = BeautifulSoup(content, "html.parser")

print("--- Thread Header ---")
h1 = soup.find("h1")
print("H1:", h1.get_text(strip=True) if h1 else "None")

# Inspect posts/messages
articles = soup.find_all("article", class_=lambda c: c and "message" in c)
print(f"\nTotal article.message elements: {len(articles)}")

for idx, art in enumerate(articles):
    print(f"\n[Message #{idx+1}] ID: {art.get('id')}")
    author = art.find(class_=lambda c: c and "message-name" in c)
    print("  Author:", author.get_text(strip=True) if author else "None")
    
    # Message body
    body = art.find("div", class_=lambda c: c and "message-body" in c)
    if body:
        # Check text length
        text = body.get_text(strip=True)
        print(f"  Body text length: {len(text)} chars")
        print(f"  Body text sample: {text[:200]}...")
        
        # Check images inside body
        imgs = body.find_all("img")
        print(f"  Images in message body: {len(imgs)}")
        for img in imgs[:5]:
            print(f"    - img src: {img.get('src')}")
            print(f"      alt: {img.get('alt')} | class: {img.get('class')}")
            
        # Check attachments block
        attachments = art.find(class_=lambda c: c and "message-attachments" in c)
        if attachments:
            att_items = attachments.find_all(class_=lambda c: c and "attachment" in c)
            print(f"  Attachments found: {len(att_items)}")
            for att in att_items[:3]:
                print(f"    - attachment: {att.get_text(strip=True)[:60]}")

# Check comments / replies section
comments_containers = soup.find_all(class_=lambda c: c and any(k in c.lower() for k in ["comment", "response", "reply", "reaction"]))
print(f"\nPotential comment/reply containers: {len(comments_containers)}")
for cc in comments_containers[:10]:
    print(f"  Class: {cc.get('class')}")

# Check message responses (XF thread replies / message responses)
responses = soup.select(".message-responses, .message-responseRow, .comment, .structItem-cell")
print(f"Specific response selectors count: {len(responses)}")
for r in responses[:5]:
    print(f"  Response: {r.get('class')} -> {r.get_text(strip=True)[:100]}")

