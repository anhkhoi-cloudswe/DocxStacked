import asyncio
import subprocess
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

def capture_settings_screenshot():
    artifact_dir = Path(r"C:\Users\Admin\.gemini\antigravity\brain\54d3977f-6db8-412b-9d5f-bb38fade0d94")
    artifact_dir.mkdir(parents=True, exist_ok=True)

    # Start backend
    backend_proc = subprocess.Popen(
        [".venv\\Scripts\\python.exe", "-m", "uvicorn", "backend.app.main:app", "--host", "127.0.0.1", "--port", "8000"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Start frontend preview (serving dist/)
    frontend_proc = subprocess.Popen(
        ["cmd.exe", "/c", "npm", "--prefix", "frontend", "run", "preview", "--", "--port", "4173"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    time.sleep(3)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 1100})
            page.goto("http://localhost:4173")
            page.wait_for_load_state("networkidle")

            # Click Settings button
            settings_btn = page.locator("text=Cài đặt")
            if settings_btn.is_visible():
                settings_btn.click()
                time.sleep(1)

            # Capture Light mode
            light_path = artifact_dir / "04_cai_dat_light.png"
            page.screenshot(path=str(light_path), full_page=True)
            print(f"Captured light mode: {light_path}")

            # Switch to Dark mode
            toggle_btn = page.locator("header button:has-text('Tối')")
            if toggle_btn.is_visible():
                toggle_btn.click()
                time.sleep(0.5)

            dark_path = artifact_dir / "04_cai_dat_dark.png"
            page.screenshot(path=str(dark_path), full_page=True)
            print(f"Captured dark mode: {dark_path}")

            browser.close()
    finally:
        backend_proc.terminate()
        frontend_proc.terminate()

if __name__ == "__main__":
    capture_settings_screenshot()

