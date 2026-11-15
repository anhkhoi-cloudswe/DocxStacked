import time
from pathlib import Path
from playwright.sync_api import sync_playwright

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 950})
        page.goto("http://localhost:5173/")
        page.wait_for_selector("text=Cài đặt", timeout=10000)
        page.click("text=Cài đặt")
        page.wait_for_selector("text=Trí tuệ nhân tạo", timeout=10000)
        page.click("text=Trí tuệ nhân tạo")
        time.sleep(1)

        # Look for password inputs
        inputs = page.query_selector_all('input[type="password"]')
        print(f"Password inputs found: {len(inputs)}")

        if len(inputs) > 0:
            inputs[0].fill("AIzaSyDemoKey5678")
            print("Entered API key AIzaSyDemoKey5678")

        save_btn = page.locator('button:has-text("Lưu cài đặt")').first
        if save_btn.count() > 0:
            save_btn.click()
            print("Clicked save button")
            page.wait_for_selector("text=Đã lưu cấu hình thành công", timeout=10000)
            print("Saved notification displayed")

        # Reload page
        print("Reloading page...")
        page.reload()
        page.wait_for_selector("text=Cài đặt", timeout=10000)
        page.click("text=Cài đặt")
        page.wait_for_selector("text=Trí tuệ nhân tạo", timeout=10000)
        page.click("text=Trí tuệ nhân tạo")
        time.sleep(1.5)

        saved_elements = page.locator('text=Đã lưu').all_text_contents()
        print(f"Elements containing 'Đã lưu': {saved_elements}")

        thay_btns = page.locator('button:has-text("Thay")').count()
        xoa_btns = page.locator('button:has-text("Xoá")').count()
        print(f"Thay buttons: {thay_btns}, Xoá buttons: {xoa_btns}")

        out_path = Path(r"C:\Users\Admin\.gemini\antigravity\brain\4d3a7566-4917-4554-8706-6a48db8f8bf9\settings_saved.png")
        page.screenshot(path=str(out_path), full_page=True)
        print(f"Screenshot successfully saved to {out_path} ({out_path.stat().st_size} bytes)")
        browser.close()

if __name__ == "__main__":
    main()
