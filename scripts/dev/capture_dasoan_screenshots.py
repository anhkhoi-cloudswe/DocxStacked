import os
import sys
import time
import subprocess
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent.parent
EXT_PATH = ROOT / "extension"
SCREENSHOT_DIR = ROOT / "docs" / "screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

def wait_for_backend(timeout=15):
    import urllib.request
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=1) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False

def main():
    backend_proc = None
    # Check if backend is already running
    import urllib.request
    running = False
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=1) as resp:
            if resp.status == 200:
                running = True
                print("Backend already running.")
    except Exception:
        pass

    if not running:
        print("Starting backend uvicorn...")
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "backend")
        backend_proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if not wait_for_backend(20):
            print("Failed to start backend!")
            if backend_proc:
                backend_proc.kill()
            sys.exit(1)
        print("Backend started successfully.")

    profile_dir = ROOT / "tmp_capture_profile"
    try:
        with sync_playwright() as p:
            print("Launching browser with extension...")
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                headless=False,
                viewport={"width": 420, "height": 700},
                args=[
                    f"--disable-extensions-except={EXT_PATH}",
                    f"--load-extension={EXT_PATH}",
                    "--no-first-run",
                ]
            )

            # Wait for background service worker to get extension ID
            time.sleep(1.5)
            ext_id = None
            for sw in context.service_workers:
                if "chrome-extension://" in sw.url:
                    ext_id = sw.url.split("/")[2]
                    break
            
            if not ext_id:
                # If service worker not yet listed, get via extensions page or fallback
                for page in context.pages:
                    if "chrome-extension://" in page.url:
                        ext_id = page.url.split("/")[2]
                        break

            if not ext_id:
                print("Could not find extension ID from service worker, querying background...")
                sw = context.wait_for_event("serviceworker", timeout=5000)
                ext_id = sw.url.split("/")[2]

            print(f"Extension ID: {ext_id}")
            panel_url = f"chrome-extension://{ext_id}/sidepanel.html"
            page = context.new_page()
            page.set_viewport_size({"width": 420, "height": 700})
            page.goto(panel_url)
            page.wait_for_load_state("networkidle")

            # Click Tab 2: "Đã soạn"
            print("Switching to tab 'Đã soạn'...")
            page.click('[data-tab="dasoan"]')
            page.wait_for_selector(".dasoan-group", timeout=8000)
            time.sleep(1.0)

            # 1. Screenshot 1: default collapsed
            img1_path = SCREENSHOT_DIR / "screenshot_dasoan_collapsed.png"
            page.screenshot(path=str(img1_path))
            print(f"Captured: {img1_path}")

            # 2. Click PRN232 header to expand it
            print("Expanding PRN232...")
            prn_header = page.locator('.dasoan-group[data-subject="PRN232"] .dasoan-group-header')
            prn_header.click()
            page.wait_for_selector('.dasoan-group[data-subject="PRN232"] .dasoan-group-docs.expanded', timeout=3000)
            time.sleep(0.5)

            # Screenshot 2: one group expanded
            img2_path = SCREENSHOT_DIR / "screenshot_dasoan_expanded.png"
            page.screenshot(path=str(img2_path))
            print(f"Captured: {img2_path}")

            # 3. Type "prn" into search box
            print("Searching 'prn'...")
            search_input = page.locator("#input-search-dasoan")
            search_input.fill("prn")
            time.sleep(0.5)

            # Screenshot 3: searching "prn"
            img3_path = SCREENSHOT_DIR / "screenshot_dasoan_search_prn.png"
            page.screenshot(path=str(img3_path))
            print(f"Captured: {img3_path}")

            context.close()
            print("Browser closed.")

    finally:
        if backend_proc:
            backend_proc.kill()
            print("Backend stopped.")
        # Clean profile
        try:
            import shutil
            if profile_dir.exists():
                shutil.rmtree(profile_dir, ignore_errors=True)
        except Exception:
            pass

if __name__ == "__main__":
    main()
