import urllib.request, ssl, re

pe_urls = [
    "https://fuoverflow.com/threads/csd202-pe-su26-paper-1.6983/",
    "https://fuoverflow.com/threads/csd202-sp26-pe-5.5913/",
]

ctx = ssl.create_default_context()
headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

for u in pe_urls:
    print(f"\nChecking: {u}")
    req = urllib.request.Request(u, headers=headers)
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
            txt = r.read().decode("utf-8")
            files = re.findall(r'class="file-name"[^>]*>(.*?)</span>', txt)
            imgs = re.findall(r'src="(https://data\.fuoverflow\.com/attachments/[^"]+)"', txt)
            print("  Files:", files)
            print(f"  Images count: {len(imgs)}")
            for im in imgs[:5]:
                print(f"    - {im}")
    except Exception as e:
        print(f"  Error: {e}")

