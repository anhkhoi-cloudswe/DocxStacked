import asyncio
import os
import sys
from pathlib import Path
from playwright.async_api import async_playwright
from PIL import Image

EXT_PATH = os.path.abspath("extension")
USER_DATA_DIR = os.path.abspath("temp_ext_user_data_capture")
OUTPUT_DIR = os.path.abspath("data/inspect_prn232/action_bar_states")
WIDTHS = [320, 400, 500]
HEIGHT = 700

async def capture_action_bar():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    print("=== CAPTURING 3 ACTION BAR STATES (320px, 400px, 500px) ===")

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
        await page.wait_for_selector("#backend-status:has-text('Online')", timeout=15000)
        await asyncio.sleep(1)

        # Select PRN232
        print("Selecting subject PRN232...")
        await page.click("#input-subject-combobox")
        await page.fill("#input-subject-combobox", "PRN232")
        await page.wait_for_selector("#subject-dropdown .combobox-item", timeout=5000)
        item = page.locator("#subject-dropdown .combobox-item", has_text="PRN232").first
        await item.click()
        await page.wait_for_selector("#chonde-list-container .doc-item", timeout=10000)
        await asyncio.sleep(1)

        # Filter FE-RE
        btn_fe = page.locator(".filter-chip-btn[data-type='FE']").first
        await btn_fe.click()
        await asyncio.sleep(0.5)

        # Helper to uncheck all
        async def uncheck_all():
            await page.evaluate("""() => {
                chondeState.selectedUrls.clear();
                renderExamList();
            }""")
            await asyncio.sleep(0.3)

        # Helper to check by title substring
        async def check_by_title(sub):
            await page.evaluate("""(sub) => {
                const ex = chondeState.exams.find(e => e.title.includes(sub));
                if (ex) {
                    chondeState.selectedUrls.add(ex.url);
                    renderExamList();
                }
            }""", sub)
            await asyncio.sleep(0.3)

        # ==========================================
        # STATE 1: Chỉ có đề chưa soạn -> "Soạn N đề"
        # ==========================================
        print("\n--- State 1: Chỉ có đề chưa soạn ---")
        await uncheck_all()
        await check_by_title("PRN232 - SU26 - FE")
        await asyncio.sleep(0.5)

        for w in WIDTHS:
            await page.set_viewport_size({"width": w, "height": HEIGHT})
            await asyncio.sleep(0.4)
            out_file = os.path.join(OUTPUT_DIR, f"state1_uncompiled_{w}px.png")
            await page.screenshot(path=out_file)
            print(f" Captured State 1 ({w}px): {out_file}")

        # ==========================================
        # STATE 2: Chỉ có đề đã soạn -> "Cập nhật N đề" và "Tải ZIP"
        # ==========================================
        print("\n--- State 2: Chỉ có đề đã soạn ---")
        await uncheck_all()
        await check_by_title("SU25 - Final Exam")
        await check_by_title("SU26 - B5 - FE")
        await asyncio.sleep(0.5)

        for w in WIDTHS:
            await page.set_viewport_size({"width": w, "height": HEIGHT})
            await asyncio.sleep(0.4)
            out_file = os.path.join(OUTPUT_DIR, f"state2_compiled_{w}px.png")
            await page.screenshot(path=out_file)
            print(f" Captured State 2 ({w}px): {out_file}")

        # ==========================================
        # STATE 3: Trộn cả hai -> "Soạn X · Cập nhật Y" và "Tải ZIP"
        # ==========================================
        print("\n--- State 3: Trộn (1 chưa soạn + 2 đã soạn) ---")
        await check_by_title("PRN232 - SU26 - FE")
        await asyncio.sleep(0.5)

        for w in WIDTHS:
            await page.set_viewport_size({"width": w, "height": HEIGHT})
            await asyncio.sleep(0.4)
            out_file = os.path.join(OUTPUT_DIR, f"state3_mixed_{w}px.png")
            await page.screenshot(path=out_file)
            print(f" Captured State 3 ({w}px): {out_file}")

        await context.close()

    # Generate a contact sheet of the 3 states at 400px
    print("\nCreating combined contact sheet...")
    img1 = Image.open(os.path.join(OUTPUT_DIR, "state1_uncompiled_400px.png"))
    img2 = Image.open(os.path.join(OUTPUT_DIR, "state2_compiled_400px.png"))
    img3 = Image.open(os.path.join(OUTPUT_DIR, "state3_mixed_400px.png"))
    
    total_w = img1.width + img2.width + img3.width + 20
    max_h = max(img1.height, img2.height, img3.height)
    sheet = Image.new("RGB", (total_w, max_h), (24, 24, 27))
    sheet.paste(img1, (0, 0))
    sheet.paste(img2, (img1.width + 10, 0))
    sheet.paste(img3, (img1.width + img2.width + 20, 0))
    
    sheet_path = os.path.join(OUTPUT_DIR, "contact_sheet_action_bar_3states.png")
    sheet.save(sheet_path)
    print(f" Contact sheet saved: {sheet_path}")
    print("Done!")

if __name__ == "__main__":
    asyncio.run(capture_action_bar())
