import time
from playwright.sync_api import sync_playwright

def run():
    print("Launching Chromium to capture UI screens...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 850})
        page = context.new_page()

        # 1. Screen 1: Chọn môn (Light Theme)
        print("Navigating to http://localhost:5173/...")
        page.goto("http://localhost:5173/", wait_until="networkidle")
        time.sleep(1)
        page.screenshot(path="docs/screenshots/01_chon_mon.png")
        print("Captured docs/screenshots/01_chon_mon.png")

        # Toggle Dark mode & capture Screen 1 Dark
        theme_btn = page.locator("button:has-text('Tối'), button:has-text('Sáng')").first
        if theme_btn.is_visible():
            theme_btn.click()
            time.sleep(0.5)
            page.screenshot(path="docs/screenshots/01_chon_mon_dark.png")
            print("Captured docs/screenshots/01_chon_mon_dark.png")
            # Toggle back to light
            theme_btn.click()
            time.sleep(0.5)

        # Set limit slider to 1 exam for rapid vertical slice demo
        slider = page.locator("input[type='range']")
        if slider.is_visible():
            slider.fill("1")
            time.sleep(0.5)

        # Click Start Button
        start_btn = page.locator("button:has-text('Bắt đầu biên soạn đề')")
        print("Clicking 'Bắt đầu biên soạn đề'...")
        start_btn.click()

        # 2. Screen 2: Tiến trình
        print("Waiting for Screen 2 (Tiến trình)...")
        page.wait_for_selector("text=Đang biên soạn tài liệu ôn tập", timeout=15000)
        time.sleep(3)
        page.screenshot(path="docs/screenshots/02_tien_trinh.png")
        print("Captured docs/screenshots/02_tien_trinh.png")

        # 3. Wait for completion (Screen 3: Kết quả)
        print("Waiting for job to complete (Screen 3)...")
        page.wait_for_selector("text=Hoàn tất biên soạn", timeout=240000)
        time.sleep(2)
        page.screenshot(path="docs/screenshots/03_ket_qua.png")
        print("Captured docs/screenshots/03_ket_qua.png")

        browser.close()
        print("Done capturing screenshots.")

if __name__ == "__main__":
    run()
