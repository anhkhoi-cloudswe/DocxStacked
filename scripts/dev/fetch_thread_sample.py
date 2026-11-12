import re
import urllib.request
import ssl
from pathlib import Path

urls = [
    ("fe_csd202", "https://fuoverflow.com/threads/csd202-su26-fe.7086/"),
    ("pe_csd202", "https://fuoverflow.com/threads/csd202-su26-b1-pe-paper-8.7015/"),
]

ctx = ssl.create_default_context()
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

for name, url in urls:
    print(f"\n=======================================================")
    print(f"Fetching thread: {name} -> {url}")
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=15) as res:
            print(f"Status: {res.status}")
            print(f"Final URL: {res.geturl()}")
            content = res.read().decode("utf-8", errors="ignore")
            
            # Save fixture
            fixture_path = Path(f"data/fixtures/sample_thread_{name}.html")
            fixture_path.write_text(content, encoding="utf-8")
            print(f"Saved fixture to {fixture_path}")
            
            # Check Title
            t = re.search(r"<title>(.*?)</title>", content)
            print("Title:", t.group(1) if t else "")
            
            # Check login required message or permission error
            if "Bạn không có quyền xem" in content or "You do not have permission" in content:
                print("[ALERT] Permission denied: Login required to view this thread content!")
            elif "Đăng nhập" in content and "data-logged-in=\"false\"" in content:
                print("Note: data-logged-in is false")

            # Check XenForo posts / messages
            messages = re.findall(r'<article\b[^>]*class=["\'][^"\']*message\b[^"\']*["\'][^>]*>', content)
            print(f"Messages/Posts found on page: {len(messages)}")

            # Check images
            imgs = re.findall(r'<img\b[^>]*src=["\']([^"\']+)["\'][^>]*>', content)
            print(f"Images count: {len(imgs)}")
            for img in imgs[:8]:
                print(f"  Img: {img}")

            # Check pagination / next page
            nav_next = re.search(r'<a\b[^>]*class=["\'][^"\']*pageNav-jump--next[^"\']*["\'][^>]*href=["\']([^"\']+)["\']', content)
            if nav_next:
                print(f"Pagination next link: {nav_next.group(1)}")
            else:
                print("No pagination next link found (single page or no next)")

    except Exception as e:
        print(f"Error fetching {url}: {e}")

