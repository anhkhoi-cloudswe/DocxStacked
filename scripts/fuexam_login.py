#!/usr/bin/env python3
"""
scripts/fuexam_login.py
Công cụ đăng nhập và quản lý phiên cho diễn đàn fuexam.me qua cửa sổ Chromium hiển thị (Headed).

Cách dùng:
    1. Mở cửa sổ Chromium hiển thị để người dùng tự gõ tài khoản/mật khẩu:
       python scripts/fuexam_login.py

    2. Kiểm tra trạng thái phiên:
       python scripts/fuexam_login.py --status

    3. Đăng xuất (xoá tệp phiên):
       python scripts/fuexam_login.py --logout
"""

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Dict, List, Optional, Set

import psutil

# Đảm bảo UTF-8 trên Windows console
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_AUTH_DIR = DATA_DIR / "auth"
PROFILE_DIR = DATA_DIR / "browser_profile_fuexam"
STORAGE_STATE_FILE = DATA_AUTH_DIR / "fuexam_storage_state.json"
LOG_FILE = DATA_DIR / "logs" / "fuexam_login.log"


def append_log(message: str, level: str = "INFO"):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] [{level}] {message}"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except Exception:
        pass


def set_owner_only_permissions(path: Path):
    """Giới hạn quyền đọc/ghi tệp chỉ cho chủ sở hữu hiện tại."""
    if not path.exists():
        return
    if sys.platform == "win32":
        username = os.environ.get("USERNAME")
        if username:
            try:
                cmd = ["icacls", str(path), "/inheritance:r", "/grant:r", f"{username}:(F)"]
                subprocess.run(cmd, capture_output=True, check=False)
            except Exception as e:
                append_log(f"Không thể gán quyền NTFS qua icacls: {e}", level="WARNING")
    else:
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass


def terminate_profile_locks(profile_dir: Path) -> List[int]:
    """Giải phóng các tiến trình đang khóa thư mục profile fuexam."""
    target = str(profile_dir.resolve()).lower()
    killed = []
    current_pid = os.getpid()

    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            if proc.info["pid"] == current_pid:
                continue
            cmdline = proc.info.get("cmdline") or []
            cmd_str = " ".join(cmdline).lower()
            if target in cmd_str:
                p = psutil.Process(proc.info["pid"])
                p.kill()
                killed.append(proc.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    if killed:
        time.sleep(1.0)
    return killed


def check_status() -> str:
    """
    Kiểm tra trạng thái phiên fuexam.me.
    Trả về một trong 3 chuỗi: logged_in, expired, logged_out.
    """
    if not STORAGE_STATE_FILE.exists():
        return "logged_out"

    cookies_dict = {}
    if STORAGE_STATE_FILE.exists():
        try:
            state_data = json.loads(STORAGE_STATE_FILE.read_text(encoding="utf-8"))
            for c in state_data.get("cookies", []):
                cookies_dict[c["name"]] = c["value"]
        except Exception:
            pass

    has_xf_cookie = any(k in cookies_dict for k in ("xf_user", "xf_session", "xf_user_session"))
    if not has_xf_cookie:
        return "logged_out"

    import requests
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "vi,en-US;q=0.9,en;q=0.8",
    }
    # Dùng public thread hoặc public media page, KHÔNG gọi /account/ theo yêu cầu bảo mật quyền riêng tư
    probe_url = "https://fuexam.me/threads/prm393-su26-fe-re.941/"
    try:
        resp = requests.get(probe_url, cookies=cookies_dict, headers=headers, allow_redirects=True, timeout=15)
        if resp.status_code == 200 and "/login" not in resp.url and 'data-logged-in="true"' in resp.text:
            return "logged_in"
        else:
            return "expired"
    except Exception as e:
        append_log(f"Lỗi khi gửi probe request: {e}", level="WARNING")
        return "expired"


def do_logout():
    """Xoá tệp phiên đăng nhập của fuexam.me."""
    deleted = False
    if STORAGE_STATE_FILE.exists():
        STORAGE_STATE_FILE.unlink(missing_ok=True)
        deleted = True

    if deleted:
        print("Đã đăng xuất fuexam.me thành công (đã xoá tệp phiên).")
    else:
        print("Chưa có phiên đăng nhập fuexam.me nào được lưu.")


def run_login_headed(browser_choice: str = "chromium"):
    """
    Chạy trình duyệt Chromium headed để người dùng tự gõ thông tin đăng nhập.
    Tự động phát hiện khi đăng nhập thành công và lưu cookie vào tệp phiên.
    """
    DATA_AUTH_DIR.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    terminate_profile_locks(PROFILE_DIR)

    from playwright.sync_api import sync_playwright

    channel_map = {
        "chromium": (None, "Playwright Chromium"),
        "chrome": ("chrome", "Google Chrome"),
        "msedge": ("msedge", "Microsoft Edge"),
    }
    channel_key, display_name = channel_map.get(browser_choice.lower(), (None, "Playwright Chromium"))

    login_url = "https://fuexam.me/login/"
    print(f"Đang khởi động cửa sổ {display_name}...")

    with sync_playwright() as p:
        context = None
        try:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR.resolve()),
                channel=channel_key,
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--start-maximized",
                    "--no-sandbox",
                ],
                no_viewport=True,
            )
        except Exception as e:
            print(f"[!] Không thể mở {display_name}: {e}. Đang chuyển sang Playwright Chromium...")
            try:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(PROFILE_DIR.resolve()),
                    channel=None,
                    headless=False,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--start-maximized",
                        "--no-sandbox",
                    ],
                    no_viewport=True,
                )
                display_name = "Playwright Chromium"
            except Exception as e2:
                print(f"Lỗi: Không thể mở trình duyệt: {e2}")
                sys.exit(1)

        page = context.pages[0] if context.pages else context.new_page()

        try:
            page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
            page.bring_to_front()
        except Exception as e:
            print(f"Lỗi khi điều hướng tới trang đăng nhập: {e}")
            context.close()
            sys.exit(1)

        print("=" * 65)
        print(f"[✓] CỬA SỔ {display_name.upper()} ĐÃ MỞ!")
        print(f"    Địa chỉ: {login_url}")
        print("    Vui lòng nhập tài khoản / mật khẩu trên cửa sổ trình duyệt.")
        print("    Hệ thống đang tự động theo dõi (tối đa 5 phút)...")
        print("=" * 65)

        timeout_seconds = 300
        start_time = time.time()
        authenticated = False

        while time.time() - start_time < timeout_seconds:
            time.sleep(1.5)

            try:
                open_pages = [pg for pg in context.pages if not pg.is_closed()]
                if not open_pages:
                    print("\nHuỷ (Người dùng đã đóng cửa sổ trình duyệt trước khi hoàn tất).")
                    context.close()
                    sys.exit(0)
            except Exception:
                pass

            try:
                active_page = context.pages[0] if context.pages else None
                if active_page and not active_page.is_closed():
                    logged_in_attr = active_page.evaluate(
                        "() => document.documentElement.getAttribute('data-logged-in')"
                    )
                    curr_url = active_page.url

                    if logged_in_attr == "true":
                        authenticated = True
                        break

                    cookies = context.cookies()
                    has_user = any(
                        c.get("name") in ("xf_user", "xf_session", "xf_user_session")
                        and c.get("value")
                        for c in cookies
                    )
                    if has_user and "/login" not in curr_url:
                        authenticated = True
                        break
            except Exception:
                pass

        if authenticated:
            context.storage_state(path=str(STORAGE_STATE_FILE))
            set_owner_only_permissions(STORAGE_STATE_FILE)

            print("\n" + "=" * 65)
            print("Đăng nhập thành công! Đã lưu phiên làm việc an toàn.")
            print(f"Tệp phiên: {STORAGE_STATE_FILE}")
            print("=" * 65)
            context.close()
            sys.exit(0)
        else:
            print("\nHết thời gian (Quá thời hạn chờ 5 phút mà chưa hoàn tất đăng nhập).")
            context.close()
            sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Công cụ đăng nhập fuexam.me")
    parser.add_argument(
        "--browser",
        choices=["chromium", "chrome", "msedge"],
        default="chromium",
        help="Chọn loại trình duyệt cho cửa sổ đăng nhập (mặc định: chromium)",
    )
    parser.add_argument("--status", action="store_true", help="Kiểm tra trạng thái phiên: logged_in / expired / logged_out")
    parser.add_argument("--logout", action="store_true", help="Đăng xuất, xoá phiên lưu trữ")
    args = parser.parse_args()

    if args.status:
        st = check_status()
        print(st)
    elif args.logout:
        do_logout()
    else:
        run_login_headed(browser_choice=args.browser)


if __name__ == "__main__":
    main()
