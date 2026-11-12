from backend.app.modules.crawler.browser import get_browser_manager

bm = get_browser_manager()
ctx = bm.start_context(headless=True)
cookies = ctx.cookies()
print(f"Total cookies: {len(cookies)}")
for c in cookies:
    print(f"  {c['name']} (domain: {c['domain']}, expires: {c.get('expires')})")
bm.close()

