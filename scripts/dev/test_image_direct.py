import urllib.request, ssl
from playwright.sync_api import sync_playwright
from pathlib import Path

profile_dir = Path("data/browser_profile").resolve()
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(user_data_dir=str(profile_dir), channel="chrome", headless=True)
    cookies = {c["name"]: c["value"] for c in ctx.cookies()}
    cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])
    
    # 1. Test image URL: /media/q1-webp.134314/full?fuo_h=...
    full_url = "https://fuoverflow.com/media/q1-webp.134314/full?fuo_h=f1bb276ce959f09c&fuo_e=1794461175"
    print("Testing full media image URL with cookies:", full_url)
    
    # Via ctx.request
    resp = ctx.request.get(full_url)
    print("ctx.request status:", resp.status)
    print("ctx.request content-type:", resp.headers.get("content-type"))
    print("ctx.request body len:", len(resp.body()))
    
    # Via urllib without cookie
    headers_no_c = {"User-Agent": "Mozilla/5.0"}
    try:
        req = urllib.request.Request(full_url, headers=headers_no_c)
        with urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=10) as r:
            print("urllib NO cookie status:", r.status, "len:", len(r.read()))
    except Exception as e:
        print("urllib NO cookie error:", e)

    # Via urllib WITH cookie
    headers_c = {"User-Agent": "Mozilla/5.0", "Cookie": cookie_str}
    try:
        req = urllib.request.Request(full_url, headers=headers_c)
        with urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=10) as r:
            print("urllib WITH cookie status:", r.status, "len:", len(r.read()))
    except Exception as e:
        print("urllib WITH cookie error:", e)

    # 2. Test CDN thumbnail:
    cdn_thumb = "https://data.fuoverflow.com/xfmg/thumbnail/134/134314-64461a5a0e15cc9acab495eb5b913fa7.jpg?1785602626"
    print("\nTesting CDN thumbnail:", cdn_thumb)
    try:
        req = urllib.request.Request(cdn_thumb, headers=headers_no_c)
        with urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=10) as r:
            print("CDN thumb NO cookie status:", r.status, "content-type:", r.headers.get("content-type"), "len:", len(r.read()))
    except Exception as e:
        print("CDN thumb error:", e)

    ctx.close()

