import re
import urllib.request
import ssl
from pathlib import Path

url = "https://fuoverflow.com/forums/CSD202/"
print(f"Fetching sample subject forum: {url}")

ctx = ssl.create_default_context()
req = urllib.request.Request(
    url,
    headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
)

try:
    with urllib.request.urlopen(req, context=ctx, timeout=15) as res:
        print(f"Status: {res.status}")
        print(f"Final URL: {res.geturl()}")
        content = res.read().decode("utf-8", errors="ignore")
        
        # Save as fixture
        fixture_path = Path("data/fixtures/sample_subject_csd202.html")
        fixture_path.write_text(content, encoding="utf-8")
        print(f"Saved fixture to {fixture_path}")
        
        # Title
        t = re.search(r"<title>(.*?)</title>", content)
        print("Page Title:", t.group(1) if t else "")
        
        # Check threads
        threads = re.findall(r'<div\b[^>]*class=["\'][^"\']*structItem--thread[^"\']*["\'][^>]*>(.*?)</div>\s*</div>', content, re.DOTALL)
        print(f"StructItem threads found: {len(threads)}")
        
        # Find thread links
        thread_links = re.findall(r'<a\b[^>]*href=["\'](/threads/[^"\']+)["\'][^>]*>(.*?)</a>', content)
        print(f"Total thread links found: {len(thread_links)}")
        for href, text in thread_links[:20]:
            clean_text = re.sub(r"<[^>]+>", "", text).strip()
            print(f"  {clean_text:50} -> {href}")

        # Check prefixes / labels (FE / PE badges)
        prefixes = re.findall(r'<span\b[^>]*class=["\'][^"\']*label[^"\']*["\'][^>]*>(.*?)</span>', content)
        print(f"Labels / Prefixes found: {len(prefixes)}")
        for p in set(prefixes[:10]):
            clean_p = re.sub(r"<[^>]+>", "", p).strip()
            print(f"  Label: {clean_p}")

except Exception as e:
    print(f"Error fetching subject: {e}")

