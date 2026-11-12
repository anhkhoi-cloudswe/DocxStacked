import urllib.request, ssl, re

subjects = ["PRN212", "MAS291", "SWT301", "MAE101"]
ctx = ssl.create_default_context()
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

for s in subjects:
    url = f"https://fuoverflow.com/forums/{s}/"
    print(f"\nSubject: {s} -> {url}")
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
            txt = r.read().decode("utf-8")
            threads = re.findall(r'<a\b[^>]*href=["\'](/threads/[^"\']+)["\'][^>]*>(.*?)</a>', txt)
            labels = re.findall(r'<span\b[^>]*class=["\'][^"\']*label[^"\']*["\'][^>]*>(.*?)</span>', txt)
            print(f"  Status: {r.status} | Threads found: {len(threads)//2} | Labels: {set([re.sub(r'<[^>]+>', '', l).strip() for l in labels])}")
            for href, title in threads[:6]:
                clean_title = re.sub(r'<[^>]+>', '', title).strip()
                if not any(k in href for k in ["/latest", "/unread"]):
                    print(f"    - {clean_title} -> {href}")
    except Exception as e:
        print(f"  Error: {e}")

