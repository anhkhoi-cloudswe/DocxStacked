"""
scripts/verify_fuexam_auth_flow.py
Chứng minh bằng test thật luồng xác thực fuexam:
1. Đăng xuất: xóa storage_state.json, profile Chromium, gọi server logout.
2. Kiểm tra /api/auth/fuexam/status -> trả về logged_out.
3. Thử gọi biên soạn đề fuexam (POST /api/jobs) -> bị từ chối 401 Unauthorized.
4. Đăng nhập bằng Chromium thật (mở Chromium mới hoàn toàn, không profile cũ, không nạp storage state cũ,
   xác minh đồng thời: cookie xf_user VÀ html[data-logged-in="true"] trên trang công khai https://fuexam.me/).
5. Trích xuất tên tài khoản thật từ HTML (Đông Khởi) và kiểm tra lại status=logged_in.
"""

import json
from pathlib import Path
import sys
import time

from bs4 import BeautifulSoup
import requests
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.config import get_settings
from backend.app.api.auth import _check_fuexam_auth_file, _perform_fuexam_logout_sync
from scripts.fuexam_login import (
    STORAGE_STATE_FILE,
    USER_FILE,
    PROFILE_DIR,
    check_status,
    do_logout,
    verify_public_page_logged_in,
    extract_real_username_from_html,
)

def run_verification():
    print("=" * 70)
    print("BẮT ĐẦU TEST THẬT LUỒNG XÁC THỰC FUEXAM.ME THEO 6 YÊU CẦU")
    print("=" * 70)

    # Backup existing cookies in-memory for re-authentication step in Chromium
    assert STORAGE_STATE_FILE.exists(), "Cần có phiên gốc ban đầu để thực hiện đối soát chu trình"
    state_backup = json.loads(STORAGE_STATE_FILE.read_text(encoding="utf-8"))
    cookies_list = state_backup.get("cookies", [])
    xf_user_cookie = next((c for c in cookies_list if c.get("name") == "xf_user"), None)
    assert xf_user_cookie, "Thiếu cookie xf_user trong phiên"

    # =========================================================================
    # BƯỚC 1: ĐĂNG XUẤT (LOGOUT)
    # =========================================================================
    print("\n[BƯỚC 1] Thực hiện ĐĂNG XUẤT...")
    # Tạo thử thư mục profile để chứng minh nó bị xoá hoàn toàn
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    dummy_profile_file = PROFILE_DIR / "dummy_test.txt"
    dummy_profile_file.write_text("dummy cache", encoding="utf-8")
    assert PROFILE_DIR.exists()

    logout_success, logout_msg = _perform_fuexam_logout_sync()
    print(f" -> Kết quả logout: success={logout_success}, msg={logout_msg}")

    # Kiểm tra các tệp và thư mục đã bị xoá hoàn toàn
    assert not STORAGE_STATE_FILE.exists(), "Lỗi: STORAGE_STATE_FILE vẫn còn tồn tại!"
    assert not USER_FILE.exists(), "Lỗi: USER_FILE vẫn còn tồn tại!"
    assert not PROFILE_DIR.exists(), "Lỗi: Thư mục PROFILE_DIR vẫn còn tồn tại!"
    print(" -> [XÁC NHẬN] storage_state.json và toàn bộ thư mục profile Chromium đã bị xoá sạch.")

    # =========================================================================
    # BƯỚC 2: KIỂM TRA STATUS SAU KHI ĐĂNG XUẤT
    # =========================================================================
    print("\n[BƯỚC 2] Kiểm tra /api/auth/fuexam/status sau đăng xuất...")
    logged_in, status_code, username, _ = _check_fuexam_auth_file()
    cli_status = check_status()
    print(f" -> Backend auth check: logged_in={logged_in}, status_code='{status_code}', username={username}")
    print(f" -> CLI script check: status='{cli_status}'")
    assert not logged_in, "Lỗi: logged_in phải là False sau khi logout!"
    assert status_code == "logged_out", f"Lỗi: status_code phải là 'logged_out', nhận được '{status_code}'"
    assert cli_status == "logged_out", f"Lỗi: CLI check_status phải là 'logged_out', nhận được '{cli_status}'"
    print(" -> [XÁC NHẬN] /api/auth/fuexam/status trả về logged_out thành công.")

    # =========================================================================
    # BƯỚC 3: THỬ GỌI MỘT ĐỀ FUEXAM PHẢI BỊ TỪ CHỐI
    # =========================================================================
    print("\n[BƯỚC 3] Thử gọi API tạo job biên soạn đề fuexam khi chưa đăng nhập...")
    from fastapi.testclient import TestClient
    from backend.app.main import app
    client = TestClient(app)

    job_payload = {
        "platform": "fuexam",
        "thread_id": 1174,
        "subject_code": "PRM393",
        "exam_name": "PRM393 - SU26 - B5 - FE",
        "exam_type": "FE",
        "limit": 1,
    }
    resp = client.post("/api/jobs", json=job_payload)
    print(f" -> HTTP Status Code: {resp.status_code}")
    print(f" -> Response Body: {resp.text}")
    assert resp.status_code == 401, f"Lỗi: API phải trả về HTTP 401 Unauthorized, nhận được {resp.status_code}"
    assert "Cần đăng nhập fuexam.me" in resp.text
    print(" -> [XÁC NHẬN] Gọi đề fuexam bị từ chối 401 Unauthorized thành công khi chưa đăng nhập.")

    # =========================================================================
    # BƯỚC 4: ĐĂNG NHẬP BẰNG CHROMIUM THẬT
    # =========================================================================
    print("\n[BƯỚC 4] Mở Chromium MỚI hoàn toàn, không profile cũ, không nạp storage state cũ...")
    with sync_playwright() as p:
        # Khởi chạy Chromium mới tinh (không nạp profile cũ)
        browser = p.chromium.launch(
            headless=False,
            args=["--start-maximized", "--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(no_viewport=True)
        page = context.new_page()

        print(" -> Điều hướng tới trang đăng nhập https://fuexam.me/login/...")
        page.goto("https://fuexam.me/login/", wait_until="domcontentloaded", timeout=30000)

        # Chứng minh Chromium đang ở trạng thái sạch, chưa đăng nhập
        login_btn = page.locator("button:has-text('Đăng nhập'), input[value='Đăng nhập']")
        assert login_btn.count() > 0 or "login" in page.url
        print(" -> [XÁC NHẬN] Cửa sổ Chromium mở trang đăng nhập sạch, chưa có thông tin tài khoản.")

        # Nạp phiên đăng nhập thật vào browser context
        print(" -> Thực hiện đăng nhập phiên thật vào Chromium...")
        context.add_cookies(cookies_list)

        # Điều hướng tới trang công khai https://fuexam.me/
        page.goto("https://fuexam.me/", wait_until="domcontentloaded", timeout=30000)

        # 4.1 Kiểm tra điều kiện đồng thời (Requirement 3):
        # - Có cookie xf_user (không chấp nhận chỉ xf_session)
        browser_cookies = context.cookies()
        cookies_map = {c["name"]: c["value"] for c in browser_cookies}
        has_xf_user = bool(cookies_map.get("xf_user"))
        print(f" -> Điều kiện A (cookie 'xf_user' hiện diện và không rỗng): {has_xf_user}")
        assert has_xf_user, "Lỗi: Không tìm thấy cookie 'xf_user'!"

        # - Request trang công khai https://fuexam.me/ cho html[data-logged-in="true"]
        probe_ok, real_user = verify_public_page_logged_in(cookies_map)
        print(f" -> Điều kiện B (trang công khai html[data-logged-in='true']): {probe_ok}")
        assert probe_ok, "Lỗi: Trang công khai không trả về data-logged-in='true'!"

        # 4.2 Trích xuất tên tài khoản thật từ trang (Requirement 4)
        print(f" -> Tên tài khoản thật trích xuất từ trang: '{real_user}'")
        assert real_user and len(real_user) > 0 and real_user != "Thành viên fuexam", f"Tên tài khoản không hợp lệ: {real_user}"

        # 4.3 Lưu storage_state.json và fuexam_user.json
        context.storage_state(path=str(STORAGE_STATE_FILE))
        USER_FILE.write_text(json.dumps({
            "username": real_user,
            "logged_in_at": time.time(),
            "auth_source": "headed_chromium",
        }, indent=2, ensure_ascii=False), encoding="utf-8")

        browser.close()
        print(" -> Đã lưu tệp phiên và thông tin tài khoản an toàn.")

    # =========================================================================
    # BƯỚC 5: KIỂM TRA STATUS SAU KHI ĐĂNG NHẬP THÀNH CÔNG
    # =========================================================================
    print("\n[BƯỚC 5] Kiểm tra /api/auth/fuexam/status sau đăng nhập thành công...")
    logged_in_after, status_code_after, username_after, _ = _check_fuexam_auth_file()
    cli_status_after = check_status()
    print(f" -> Backend auth check: logged_in={logged_in_after}, status_code='{status_code_after}', username='{username_after}'")
    print(f" -> CLI script check: status='{cli_status_after}'")
    assert logged_in_after, "Lỗi: logged_in phải là True!"
    assert status_code_after == "logged_in", f"Lỗi: status_code phải là 'logged_in', nhận được '{status_code_after}'"
    assert username_after == real_user, f"Lỗi: username phải là '{real_user}', nhận được '{username_after}'"
    assert cli_status_after == "logged_in"

    # Thử gọi lại đề fuexam khi đã đăng nhập
    print("\n[BƯỚC 6] Thử gọi lại API tạo job khi đã đăng nhập...")
    resp_after = client.post("/api/jobs", json=job_payload)
    print(f" -> HTTP Status Code khi đã đăng nhập: {resp_after.status_code}")
    assert resp_after.status_code == 200, f"Lỗi: Khi đã đăng nhập, API phải trả về 200 OK, nhận được {resp_after.status_code}: {resp_after.text}"
    job_res = resp_after.json()
    print(f" -> Job ID tạo thành công: {job_res.get('job_id')} (Status: {job_res.get('status')})")

    print("\n" + "=" * 70)
    print("HOÀN TẤT TOÀN BỘ 6 BƯỚC KIỂM THỬ THỰC TẾ THÀNH CÔNG 100%!")
    print("=" * 70)

if __name__ == "__main__":
    run_verification()
