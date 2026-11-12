#!/usr/bin/env python3
"""
scripts/discover.py - Phase 0 Discovery Tool for FUOverflow

Purpose:
- Launch Chromium in headed mode with persistent profile (data/browser_profile).
- Allow manual login, solving CAPTCHA (if any), and session persistence.
- Inspect and log internal network API calls (JSON/XHR/Fetch) to data/discovery_network.jsonl.
- Capture page fixtures (HTML + Screenshot) via on-screen button or terminal command.
- Generate initial selector inspection and summary for docs/site_notes.md and backend/config/selectors.yaml.
"""

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

# Ensure immediate unbuffered output to stdout
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
PROFILE_DIR = DATA_DIR / "browser_profile"
FIXTURES_DIR = DATA_DIR / "fixtures"
NETWORK_LOG_PATH = DATA_DIR / "discovery_network.jsonl"
SELECTORS_PATH = BASE_DIR / "backend" / "config" / "selectors.yaml"
NOTES_PATH = BASE_DIR / "docs" / "site_notes.md"

TARGET_URL = "https://fuoverflow.com/"

INJECTED_TOOLBAR_SCRIPT = """
(function() {
  function addFloatingToolbar() {
    if (document.getElementById('gomde-toolbar')) return;
    if (!document.body) {
      setTimeout(addFloatingToolbar, 200);
      return;
    }
    const bar = document.createElement('div');
    bar.id = 'gomde-toolbar';
    bar.style.position = 'fixed';
    bar.style.bottom = '16px';
    bar.style.right = '16px';
    bar.style.zIndex = '2147483647';
    bar.style.backgroundColor = '#1F1B16';
    bar.style.color = '#FAF7F2';
    bar.style.padding = '8px 14px';
    bar.style.borderRadius = '6px';
    bar.style.border = '1px solid #D4C5B9';
    bar.style.boxShadow = '0 6px 16px rgba(0,0,0,0.25)';
    bar.style.fontFamily = 'monospace, sans-serif';
    bar.style.fontSize = '12px';
    bar.style.display = 'flex';
    bar.style.gap = '10px';
    bar.style.alignItems = 'center';

    const title = document.createElement('span');
    title.textContent = '⚡ Gomde Discovery';
    title.style.fontWeight = 'bold';
    title.style.color = '#E5A93C';

    const btn = document.createElement('button');
    btn.id = 'gomde-save-btn';
    btn.textContent = '📸 Save Fixture';
    btn.style.backgroundColor = '#B83227';
    btn.style.color = '#FFFFFF';
    btn.style.border = 'none';
    btn.style.padding = '6px 10px';
    btn.style.borderRadius = '4px';
    btn.style.cursor = 'pointer';
    btn.style.fontWeight = 'bold';

    const status = document.createElement('span');
    status.id = 'gomde-status';
    status.textContent = '';
    status.style.color = '#78B159';
    status.style.fontSize = '11px';

    btn.onclick = async () => {
      btn.disabled = true;
      btn.textContent = 'Saving...';
      try {
        if (window.captureFixtureBinding) {
          const res = await window.captureFixtureBinding();
          status.textContent = res || 'Saved!';
        } else {
          status.textContent = 'Binding not ready';
        }
      } catch (e) {
        status.textContent = 'Error: ' + e.message;
      }
      setTimeout(() => {
        btn.disabled = false;
        btn.textContent = '📸 Save Fixture';
        setTimeout(() => { status.textContent = ''; }, 3000);
      }, 500);
    };

    bar.appendChild(title);
    bar.appendChild(btn);
    bar.appendChild(status);
    document.body.appendChild(bar);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', addFloatingToolbar);
  } else {
    addFloatingToolbar();
  }
})();
"""


def slugify(text: str) -> str:
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[-\s]+", "_", text)[:40] or "page"


def save_page_fixture(page, reason: str = "manual") -> str:
    """Save HTML and Screenshot for current page."""
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    url = page.url
    parsed = urlparse(url)
    path_slug = slugify(parsed.path.strip("/") or "home")
    title_slug = slugify(page.title())
    slug = f"{path_slug}_{title_slug}"[:50]

    html_filename = f"{timestamp}_{slug}.html"
    png_filename = f"{timestamp}_{slug}.png"

    html_path = FIXTURES_DIR / html_filename
    png_path = FIXTURES_DIR / png_filename

    html_content = page.content()
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    page.screenshot(path=str(png_path), full_page=False)

    msg = f"Saved: {html_filename}"
    print(f"\n[Fixture Captured] ({reason})")
    print(f"  URL:  {url}")
    print(f"  HTML: {html_path.relative_to(BASE_DIR)}")
    print(f"  PNG:  {png_path.relative_to(BASE_DIR)}")

    # Analyze HTML for quick hints
    analyze_fixture_hints(html_content, url)
    return msg


def analyze_fixture_hints(html: str, url: str):
    """Print hints on framework, images, questions found in HTML."""
    hints = []
    if "__NEXT_DATA__" in html:
        hints.append("Framework: Next.js (SSR / hydration state found in __NEXT_DATA__)")
    if "__NUXT__" in html:
        hints.append("Framework: Nuxt.js")
    if "vite/client" in html or "@vite" in html:
        hints.append("Framework: Vite-based SPA")

    img_count = len(re.findall(r"<img\b[^>]*>", html, re.IGNORECASE))
    hints.append(f"Images count: {img_count}")

    if "/api/" in html:
        hints.append("Contains inline references to '/api/' endpoints")

    print("  Analysis hints:")
    for h in hints:
        print(f"    - {h}")


def handle_response(response):
    """Intercept and log JSON API responses."""
    try:
        url = response.url
        content_type = response.headers.get("content-type", "")
        # Only log JSON or relevant API responses from target domain
        if "fuoverflow.com" in url:
            if "application/json" in content_type or "/api/" in url or "_next/data" in url:
                status = response.status
                method = response.request.method
                body_sample = None
                try:
                    body = response.json()
                    body_sample = body if isinstance(body, (dict, list)) else str(body)[:200]
                except Exception:
                    try:
                        body_sample = response.text()[:200]
                    except Exception:
                        pass

                entry = {
                    "timestamp": datetime.now().isoformat(),
                    "method": method,
                    "url": url,
                    "status": status,
                    "content_type": content_type,
                    "body_sample": body_sample,
                }

                with open(NETWORK_LOG_PATH, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")

                print(f"[API Network] {method} {status} {url[:100]}")
    except Exception as e:
        # Avoid crashing on background network errors
        pass


def main():
    print("=" * 65)
    print("  Gomde Discovery Script (Phase 0)")
    print("=" * 65)
    print(f"Base Directory:       {BASE_DIR}")
    print(f"Browser Profile Dir:  {PROFILE_DIR}")
    print(f"Fixtures Dir:         {FIXTURES_DIR}")
    print(f"Target URL:           {TARGET_URL}")
    print("-" * 65)

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        print("\n[1/3] Launching persistent Chromium browser (headed mode)...")
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            viewport={"width": 1366, "height": 850},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
            ],
            no_viewport=True,
        )

        # Expose binding so browser-side toolbar can call Python save
        def on_capture(source):
            page = source["page"]
            return save_page_fixture(page, reason="toolbar button")

        context.expose_binding("captureFixtureBinding", on_capture)
        context.add_init_script(INJECTED_TOOLBAR_SCRIPT)

        # Track network responses
        context.on("response", handle_response)

        page = context.pages[0] if context.pages else context.new_page()

        print(f"[2/3] Navigating to {TARGET_URL}...")
        try:
            page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=45000)
            time.sleep(2)
            # Auto-save initial landing page
            save_page_fixture(page, reason="initial_landing")
        except Exception as e:
            print(f"[Notice] Page load notice: {e}")

        print("\n[3/3] Browser is ready!")
        print("=" * 65)
        print("HƯỚNG DẪN KHẢO SÁT:")
        print("  1. Trình duyệt đã mở. Bạn có thể đăng nhập nếu cần (profile sẽ tự lưu).")
        print("  2. Di chuyển đến các trang:")
        print("     - Danh sách môn")
        print("     - Chi tiết 1 môn (danh sách đề FE / PE)")
        print("     - Chi tiết 1 đề (xem câu hỏi và comment)")
        print("  3. Trên mỗi trang quan trọng, bấm nút đỏ '[📸 Save Fixture]'")
        print("     ở góc dưới bên phải màn hình để chụp ảnh và lưu HTML fixture.")
        print("  4. Script tự động bắt và ghi nhận các API JSON ngầm vào data/discovery_network.jsonl.")
        print("  5. Khi hoàn thành khảo sát, chỉ cần ĐÓNG CỬA SỔ TRÌNH DUYỆT.")
        print("=" * 65)

        # Wait loop while the browser page remains open
        try:
            while len(context.pages) > 0:
                # Check if the primary page is still open
                all_closed = True
                for p_item in context.pages:
                    if not p_item.is_closed():
                        all_closed = False
                        break
                if all_closed:
                    break
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[Notice] KeyboardInterrupt received. Saving current page before exiting...")
            try:
                if context.pages and not context.pages[0].is_closed():
                    save_page_fixture(context.pages[0], reason="exit")
            except Exception:
                pass
        finally:
            print("\nClosing browser context and saving profile...")
            context.close()

    print("\n" + "=" * 65)
    print("Khảo sát hoàn tất! Các file đã lưu:")
    print(f"  - Browser profile:  {PROFILE_DIR}")
    fixtures = list(FIXTURES_DIR.glob("*.*"))
    print(f"  - Fixtures ({len(fixtures)} files):")
    for f in fixtures[:10]:
        print(f"      {f.name}")
    if len(fixtures) > 10:
        print(f"      ... and {len(fixtures) - 10} more")

    if NETWORK_LOG_PATH.exists():
        with open(NETWORK_LOG_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
        print(f"  - Captured API calls: {len(lines)} endpoints logged in {NETWORK_LOG_PATH.name}")

    print("=" * 65)


if __name__ == "__main__":
    main()
