import asyncio
import os
import sys
from playwright.async_api import async_playwright

EXT_PATH = os.path.abspath("extension")
USER_DATA_DIR = os.path.abspath("temp_ext_user_data_capture")
OUTPUT_DIR = os.path.abspath("temp_screenshots")
WIDTHS = [320, 400, 500]
HEIGHT = 650

async def capture_all_states():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print("=== CAPTURING REAL EXTENSION SCREENSHOTS ===")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            USER_DATA_DIR,
            headless=False,
            args=[
                f"--disable-extensions-except={EXT_PATH}",
                f"--load-extension={EXT_PATH}",
            ]
        )
        await asyncio.sleep(2)
        
        ext_id = None
        for bg in context.service_workers:
            if "chrome-extension://" in bg.url:
                ext_id = bg.url.split("/")[2]
                break
        if not ext_id:
            ext_id = "kicplcdfmbcfjildbbimpfiljlmfokea"

        sidepanel_url = f"chrome-extension://{ext_id}/sidepanel.html"
        page = await context.new_page()
        await page.goto(sidepanel_url)
        await page.wait_for_selector("#backend-status:has-text('Online')", timeout=10000)
        await asyncio.sleep(1)

        # 1. State 1: Chưa chọn môn (default view on load)
        print("Capturing State 1: Chua chon mon...")
        for w in WIDTHS:
            await page.set_viewport_size({"width": w, "height": HEIGHT})
            await asyncio.sleep(0.3)
            out_file = os.path.join(OUTPUT_DIR, f"state1_chua_chon_mon_{w}px.png")
            await page.screenshot(path=out_file)
            print(f" Saved: {out_file}")

        # 2. State 2: Đang gõ gợi ý (type 'mln' in combobox)
        print("\nCapturing State 2: Dang go goi y 'mln'...")
        await page.click("#input-subject-combobox")
        await page.fill("#input-subject-combobox", "mln")
        await page.wait_for_selector("#subject-dropdown .combobox-item", timeout=5000)
        await asyncio.sleep(0.5)
        for w in WIDTHS:
            await page.set_viewport_size({"width": w, "height": HEIGHT})
            await asyncio.sleep(0.3)
            out_file = os.path.join(OUTPUT_DIR, f"state2_go_goi_y_{w}px.png")
            await page.screenshot(path=out_file)
            print(f" Saved: {out_file}")

        # 3. State 3: Đã chọn môn có danh sách đề (click on MLN122)
        print("\nCapturing State 3: Da chon mon co danh sach de...")
        item = page.locator("#subject-dropdown .combobox-item", has_text="MLN122").first
        await item.click()
        # Wait for exam list to be rendered
        await page.wait_for_selector("#chonde-list-container .doc-item", timeout=10000)
        # Select first 2 exams
        cbs = await page.query_selector_all("#chonde-list-container .chonde-checkbox")
        if len(cbs) >= 2:
            await cbs[0].check()
            await cbs[1].check()
        await asyncio.sleep(0.5)
        for w in WIDTHS:
            await page.set_viewport_size({"width": w, "height": HEIGHT})
            await asyncio.sleep(0.3)
            out_file = os.path.join(OUTPUT_DIR, f"state3_da_chon_mon_{w}px.png")
            await page.screenshot(path=out_file)
            print(f" Saved: {out_file}")

        # 4. State 4: Đang chạy hàng đợi
        print("\nCapturing State 4: Dang chay hang doi...")
        # Simulate active queue progress card display
        await page.evaluate("""() => {
            const card = document.getElementById('queue-progress-card');
            card.style.display = 'block';
            document.getElementById('queue-progress-title').innerText = '[1/2] MLN122 - SU26 - RE';
            document.getElementById('queue-overall-ratio').innerText = '1/2';
            document.getElementById('progress-bar').style.width = '45%';
            document.getElementById('stats-summary-line').innerText = '18/40 câu · 32 bình luận · Tốc độ: 1 req / 2.0s';
            document.getElementById('queue-controls-row').style.display = 'flex';
        }""")
        await asyncio.sleep(0.5)
        for w in WIDTHS:
            await page.set_viewport_size({"width": w, "height": HEIGHT})
            await asyncio.sleep(0.3)
            out_file = os.path.join(OUTPUT_DIR, f"state4_dang_chay_hang_doi_{w}px.png")
            await page.screenshot(path=out_file)
            print(f" Saved: {out_file}")

        # 5. State 5: Backend Offline
        print("\nCapturing State 5: Backend Offline...")
        await page.evaluate("""() => {
            const status = document.getElementById('backend-status');
            status.className = 'status-chip chip-offline';
            status.innerText = 'Backend Offline';
            const notice = document.getElementById('ui-notice-box');
            notice.innerText = 'Backend Offline. Mở terminal chạy: python run_dev.py';
            notice.style.display = 'block';
            document.getElementById('btn-main-action').disabled = true;
            document.getElementById('btn-start-queue').disabled = true;
            document.getElementById('queue-progress-card').style.display = 'none';
        }""")
        await asyncio.sleep(0.5)
        for w in WIDTHS:
            await page.set_viewport_size({"width": w, "height": HEIGHT})
            await asyncio.sleep(0.3)
            out_file = os.path.join(OUTPUT_DIR, f"state5_backend_offline_{w}px.png")
            await page.screenshot(path=out_file)
            print(f" Saved: {out_file}")

        await context.close()
    print("\nALL SCREENSHOTS CAPTURED SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(capture_all_states())
