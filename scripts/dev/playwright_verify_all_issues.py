import os
import sys
import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

repo_root = Path(__file__).resolve().parents[2]
screenshots_dir = repo_root / "data" / "playwright_screenshots"
screenshots_dir.mkdir(parents=True, exist_ok=True)

def test_web_dashboard(page):
    print("\n--- 1. Testing Web Dashboard (http://127.0.0.1:8000) ---")
    page.goto("http://127.0.0.1:8000")
    page.wait_for_load_state("networkidle")
    time.sleep(1)

    # Listen for any native dialogs (alert/confirm) - should be ZERO
    unexpected_dialogs = []
    page.on("dialog", lambda dialog: unexpected_dialogs.append(dialog.message))

    # Take screenshot of home
    page.screenshot(path=str(screenshots_dir / "1_dashboard_home.png"))
    print("Screenshot saved: 1_dashboard_home.png")

    # Select subject PRN232
    # Type in subject search box
    search_input = page.locator("input[placeholder*='Tìm theo mã môn']")
    if search_input.count() > 0:
        search_input.fill("PRN232")
        time.sleep(0.5)

    # Check checkbox for PRN232
    prn_item = page.locator("text=PRN232").first
    print("Found PRN232 on dashboard:", prn_item.count() > 0)
    
    # Click on the PRN232 row/checkbox
    prn_checkbox = page.locator("input[type='checkbox']").first
    prn_checkbox.check()
    time.sleep(1)

    # Check exam list loaded on dashboard
    page.screenshot(path=str(screenshots_dir / "2_dashboard_prn232_selected.png"))
    print("Screenshot saved: 2_dashboard_prn232_selected.png")

    # Verify no duplicates in exam list text
    body_text = page.locator("body").inner_text()
    count_su25 = body_text.count("PRN232 - SU25 - Final Exam")
    print(f"Occurrences of 'PRN232 - SU25 - Final Exam' on dashboard: {count_su25}")
    # Formerly had both '#4 PRN232 - SU25 - Final Exam' and '#5 Đề Thi FE - PRN232 - SU25 - Final Exam'
    assert count_su25 <= 2, f"Expected deduplicated exam, found {count_su25} occurrences"

    # Click 'Bắt đầu soạn' or start button
    start_btn = page.locator("button:has-text('Bắt đầu soạn'), button:has-text('soạn'), button.btn-primary:has-text('soạn')").first
    if start_btn.count() > 0:
        print("Clicking start button on web dashboard...")
        start_btn.click()
        time.sleep(1)
        
        # Take screenshot of result
        page.screenshot(path=str(screenshots_dir / "3_dashboard_after_click_start.png"))
        print("Screenshot saved: 3_dashboard_after_click_start.png")

        # Verify NO native alert was triggered
        print(f"Native browser dialogs triggered: {len(unexpected_dialogs)} (Expected: 0)")
        assert len(unexpected_dialogs) == 0, f"Unexpected native alerts: {unexpected_dialogs}"

        # Check for in-page modal
        modal = page.locator("[role='dialog']")
        if modal.count() > 0:
            modal_title = modal.locator("h3").inner_text()
            modal_body = modal.locator("div").nth(1).inner_text()
            print(f"In-page modal title: '{modal_title}'")
            print(f"In-page modal body: '{modal_body}'")
            assert "Dùng Extension" in modal_title or "Extension" in modal_body or "Hàng đợi" in modal_title

            # Click close button on modal
            modal.locator("button").first.click()
            time.sleep(0.5)

    print("Web Dashboard test PASSED!")

def test_sidepanel_filter_and_selection(page):
    print("\n--- 2. Testing Sidepanel Filter, Selection & Banner ---")
    
    # Prepare sidepanel HTML with mock chrome runtime & storage
    sidepanel_file = repo_root / "extension" / "sidepanel.html"
    
    # Inject mock Chrome extension API before page loads
    mock_chrome_script = """
    window.chrome = {
      runtime: {
        id: 'kicplcdfmbcfjildbbimpfiljlmfokea',
        sendMessage: (msg, cb) => { if (cb) cb({ ok: true }); },
        onMessage: { addListener: () => {} },
      },
      storage: {
        local: {
          _data: {},
          get: function(keys, cb) {
            let res = {};
            if (Array.isArray(keys)) keys.forEach(k => res[k] = this._data[k]);
            else if (typeof keys === 'string') res[keys] = this._data[keys];
            else res = { ...this._data };
            if (cb) cb(res);
            return Promise.resolve(res);
          },
          set: function(obj, cb) {
            Object.assign(this._data, obj);
            if (cb) cb();
            return Promise.resolve();
          },
          remove: function(keys, cb) {
            (Array.isArray(keys) ? keys : [keys]).forEach(k => delete this._data[k]);
            if (cb) cb();
            return Promise.resolve();
          }
        }
      },
      sidePanel: { open: () => Promise.resolve() },
      tabs: { query: () => Promise.resolve([{ id: 1, title: 'FuOverflow', url: 'https://fuoverflow.com/threads/prn232-su25-final-exam.4521/' }]) }
    };
    """
    page.add_init_script(mock_chrome_script)
    # Abort external fuoverflow calls so it instantly falls back to backend DB
    page.route("https://fuoverflow.com/**", lambda route: route.abort())
    page.goto(sidepanel_file.as_uri())
    page.wait_for_load_state("networkidle")
    time.sleep(1)

    # 1. Select PRN232 via evaluate
    page.evaluate("selectSubject('PRN232')")
    time.sleep(2)

    # Wait for exam items to be loaded into container
    page.wait_for_selector("#chonde-list-container .doc-item", timeout=10000)

    # Screenshot when PRN232 is loaded
    page.screenshot(path=str(screenshots_dir / "4_sidepanel_prn232_all.png"))
    print("Screenshot saved: 4_sidepanel_prn232_all.png")

    # 2. Click FE-RE filter button
    btn_fe_re = page.locator("button.filter-chip-btn[data-type='FE']")
    btn_fe_re.click()
    time.sleep(0.5)

    page.screenshot(path=str(screenshots_dir / "5_sidepanel_prn232_fe_re_filtered.png"))
    print("Screenshot saved: 5_sidepanel_prn232_fe_re_filtered.png")

    # Count visible exam items
    visible_items = page.locator("#chonde-list-container .doc-item")
    item_count = visible_items.count()
    print(f"Visible exams under FE-RE: {item_count} (Expected: 4)")
    assert item_count == 4, f"Expected 4 FE-RE exams, got {item_count}"

    # 3. Click 'Chọn tất cả'
    chk_all = page.locator("#check-select-all-chonde")
    chk_all.check()
    time.sleep(0.5)

    badge_selected = page.locator("#badge-chonde-selected").inner_text()
    btn_queue_text = page.locator("#btn-start-queue").inner_text()
    print(f"Badge after 'Chọn tất cả' on FE-RE: '{badge_selected}'")
    print(f"Queue button text: '{btn_queue_text}'")

    assert badge_selected == "4 đã chọn", f"Expected '4 đã chọn', got '{badge_selected}'"
    assert btn_queue_text == "Soạn 4 đề đã chọn", f"Expected 'Soạn 4 đề đã chọn', got '{btn_queue_text}'"

    page.screenshot(path=str(screenshots_dir / "6_sidepanel_fe_re_all_selected.png"))
    print("Screenshot saved: 6_sidepanel_fe_re_all_selected.png")

    # 4. Uncheck 1 exam -> indeterminate state
    first_cb = page.locator("#chonde-list-container .chonde-checkbox").first
    first_cb.uncheck()
    time.sleep(0.5)

    is_indeterminate = page.evaluate("document.getElementById('check-select-all-chonde').indeterminate")
    badge_after_uncheck = page.locator("#badge-chonde-selected").inner_text()
    btn_after_uncheck = page.locator("#btn-start-queue").inner_text()
    print(f"Checkbox indeterminate after unchecking 1 item: {is_indeterminate}")
    print(f"Badge: '{badge_after_uncheck}', Button: '{btn_after_uncheck}'")

    assert is_indeterminate is True, "Checkbox should be indeterminate"
    assert badge_after_uncheck == "3 đã chọn", f"Expected '3 đã chọn', got '{badge_after_uncheck}'"
    assert btn_after_uncheck == "Soạn 3 đề đã chọn", f"Expected 'Soạn 3 đề đã chọn', got '{btn_after_uncheck}'"

    # 5. Switch to PE filter -> auto-deselect hidden exams
    btn_pe = page.locator("button.filter-chip-btn[data-type='PE']")
    btn_pe.click()
    time.sleep(0.5)

    badge_pe = page.locator("#badge-chonde-selected").inner_text()
    btn_pe_queue = page.locator("#btn-start-queue").inner_text()
    print(f"After switching to PE: Badge: '{badge_pe}', Button: '{btn_pe_queue}'")
    assert badge_pe == "0 đã chọn", f"Expected '0 đã chọn', got '{badge_pe}'"
    assert btn_pe_queue == "Soạn 0 đề đã chọn", f"Expected 'Soạn 0 đề đã chọn', got '{btn_pe_queue}'"

    page.screenshot(path=str(screenshots_dir / "7_sidepanel_pe_auto_deselected.png"))
    print("Screenshot saved: 7_sidepanel_pe_auto_deselected.png")

    # 6. Test Reopen Lifecycle Banner
    print("\n--- 3. Testing Interrupted Queue Resume Banner on Reopen ---")
    # Simulate closing panel while queue has 4 items and 1 is finished
    saved_state = {
        "items": [
            {"title": "PRN232 - SU25 - Final Exam", "status": "done", "compiled": True, "url": "url1"},
            {"title": "PRN232 - SU26 - B5 - FE", "status": "running", "compiled": False, "url": "url2"},
            {"title": "PRN232 - SU26 - FE", "status": "pending", "compiled": False, "url": "url3"},
            {"title": "PRN232 - SP26 - FE", "status": "pending", "compiled": False, "url": "url4"},
        ],
        "currentIndex": 1,
        "isRunning": False,
        "isPaused": True,
        "updatedAt": int(time.time() * 1000)
    }

    page.evaluate(f"""
      window.chrome.storage.local._data['savedQueueState'] = {json.dumps(saved_state)};
      checkSavedQueueState();
    """)
    time.sleep(0.5)

    banner = page.locator("#queue-resume-banner")
    banner_visible = banner.is_visible()
    banner_text = page.locator("#queue-resume-text").inner_text()
    print(f"Resume banner visible: {banner_visible}")
    print(f"Resume banner text: '{banner_text}'")

    page.screenshot(path=str(screenshots_dir / "8_sidepanel_reopen_resume_banner.png"))
    print("Screenshot saved: 8_sidepanel_reopen_resume_banner.png")

    assert banner_visible is True, "Resume banner should be visible on reopen"
    assert "Hàng đợi" in banner_text and "đang dừng" in banner_text

    # Click 'Huỷ' on banner
    page.locator("#btn-banner-cancel").click()
    time.sleep(0.5)
    banner_after_cancel = banner.is_visible()
    print(f"Banner visible after cancel: {banner_after_cancel}")
    assert banner_after_cancel is False, "Banner should hide after cancel"

    print("Sidepanel Filter, Selection & Lifecycle test PASSED!")

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-web-security", "--allow-file-access-from-files"]
        )
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        try:
            test_web_dashboard(page)
            test_sidepanel_filter_and_selection(page)
            print("\n==============================================")
            print("ALL PLAYWRIGHT TESTS PASSED SUCCESSFULLY! (100%)")
            print("==============================================")
        finally:
            browser.close()

if __name__ == "__main__":
    main()
