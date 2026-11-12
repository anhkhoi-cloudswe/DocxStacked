import re
from pathlib import Path
from html.parser import HTMLParser

html_file = list(Path("data/fixtures").glob("*.html"))[0]
content = html_file.read_text(encoding="utf-8")

print("File:", html_file.name)
title_m = re.search(r"<title>(.*?)</title>", content)
print("Title:", title_m.group(1) if title_m else "")

logged_in_m = re.search(r'data-logged-in="([^"]+)"', content)
print("data-logged-in:", logged_in_m.group(1) if logged_in_m else "")

csrf_m = re.search(r'data-csrf="([^"]+)"', content)
print("CSRF:", csrf_m.group(1) if csrf_m else "")

# Extract all links
links = re.findall(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', content, re.DOTALL | re.IGNORECASE)
print(f"Total links found: {len(links)}")

print("\n--- Auth related links ---")
for href, text in links:
    clean_text = re.sub(r"<[^>]+>", "", text).strip()
    if any(k in href.lower() for k in ["login", "register", "connected_account"]):
        print(f"  {clean_text:20} -> {href}")

print("\n--- Forum / Node links ---")
seen = set()
for href, text in links:
    clean_text = re.sub(r"<[^>]+>", "", text).strip()
    if "/forums/" in href or "/categories/" in href:
        if href not in seen:
            seen.add(href)
            print(f"  {clean_text[:40]:40} -> {href}")

