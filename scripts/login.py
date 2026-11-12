#!/usr/bin/env python3
"""
DocxStacked - FUOverflow Login Automation & Diagnostic Script
Usage:
    python scripts/login.py             # Normal headed login flow
    python scripts/login.py --diagnose  # Diagnostic check of browsers, profile locks, and logs
"""

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import time
from typing import Dict, List, Optional, Set, Tuple

import psutil

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

PROFILE_DIR = PROJECT_ROOT / "data" / "browser_profile"
COOKIES_FILE = PROJECT_ROOT / "data" / "auth" / "cookies.json"
SESSION_FILE = PROJECT_ROOT / "data" / "auth" / "login_session.json"
LOG_FILE = PROJECT_ROOT / "data" / "logs" / "login.log"


def append_login_log(message: str, level: str = "INFO"):
    """Append a log entry to data/logs/login.log without sensitive info."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{timestamp}] [{level}] {message}"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
    except Exception as e:
        print(f"Failed to write to login.log: {e}", file=sys.stderr)
    print(entry)


def update_session(state: str, message: str, browser_used: Optional[str] = None, error: Optional[str] = None):
    """Update state in data/auth/login_session.json."""
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "state": state,
        "message": message,
        "browser_used": browser_used,
        "error": error,
        "pid": os.getpid(),
        "updated_at": datetime.now().isoformat(),
    }
    try:
        SESSION_FILE.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"Failed to write session file: {e}", file=sys.stderr)


def get_session_state() -> Optional[Dict]:
    """Read current session state."""
    if not SESSION_FILE.exists():
        return None
    try:
        return json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def detect_installed_browsers() -> Dict[str, Optional[str]]:
    """Detect presence and paths of Chrome, Edge, and Playwright Chromium."""
    browsers: Dict[str, Optional[str]] = {
        "chrome": None,
        "msedge": None,
        "playwright_chromium": None,
    }

    # 1. Google Chrome
    chrome_candidates = [
        Path(os.environ.get("PROGRAMFILES", "C:\\Program Files")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
    ]
    for p in chrome_candidates:
        if p.exists():
            browsers["chrome"] = str(p)
            break

    # 2. Microsoft Edge
    edge_candidates = [
        Path(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.environ.get("PROGRAMFILES", "C:\\Program Files")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
    ]
    for p in edge_candidates:
        if p.exists():
            browsers["msedge"] = str(p)
            break

    # 3. Playwright Chromium
    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    pw_dir = local_app_data / "ms-playwright"
    if pw_dir.exists():
        for exe in pw_dir.glob("chromium-*/chrome-win*/chrome.exe"):
            browsers["playwright_chromium"] = str(exe)
            break

    return browsers


def get_locking_processes(profile_dir: Path) -> List[Tuple[int, str, str]]:
    """
    Find processes currently holding the browser profile by matching cmdline.
    Returns list of (pid, name, cmdline_summary).
    """
    target = str(profile_dir.resolve()).lower()
    locking = []
    current_pid = os.getpid()

    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if proc.info["pid"] == current_pid:
                continue
            cmdline = proc.info.get("cmdline") or []
            cmd_str = " ".join(cmdline).lower()
            if target in cmd_str:
                summary = " ".join(cmdline)[:120]
                locking.append((proc.info["pid"], proc.info["name"] or "unknown", summary))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    return locking


def terminate_profile_locks(profile_dir: Path) -> List[Tuple[int, str]]:
    """Terminate ONLY processes matching browser_profile in their cmdline."""
    locking = get_locking_processes(profile_dir)
    killed = []
    for pid, name, _ in locking:
        try:
            p = psutil.Process(pid)
            p.kill()
            killed.append((pid, name))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    if killed:
        time.sleep(1.5)  # Wait for Windows to release file handles
    return killed


def get_last_error_from_log() -> Optional[str]:
    """Retrieve the most recent ERROR line from data/logs/login.log."""
    if not LOG_FILE.exists():
        return None
    try:
        lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            if "[ERROR]" in line:
                return line
    except Exception:
        pass
    return None


def run_diagnose():
    """Run comprehensive system diagnostic and print results without secrets."""
    print("=" * 65)
    print("   DOCXSTACKED - CHẨN ĐOÁN HỆ THỐNG ĐĂNG NHẬP FUOVERFLOW")
    print("=" * 65)

    # 1. Profile directory
    abs_profile = str(PROFILE_DIR.resolve())
    print(f"\n[1] Thư mục hồ sơ trình duyệt (browser_profile):")
    print(f"    Đường dẫn : {abs_profile}")
    print(f"    Tồn tại   : {'Có' if PROFILE_DIR.exists() else 'Chưa tạo'}")

    # 2. Installed browsers
    browsers = detect_installed_browsers()
    print(f"\n[2] Trình duyệt tìm thấy trên hệ thống:")
    print(f"    - Google Chrome     : {browsers['chrome'] or 'Không tìm thấy'}")
    print(f"    - Microsoft Edge    : {browsers['msedge'] or 'Không tìm thấy'}")
    print(f"    - Playwright Chromium: {browsers['playwright_chromium'] or 'Không tìm thấy'}")

    # 3. Locking processes
    locks = get_locking_processes(PROFILE_DIR)
    print(f"\n[3] Tiến trình đang giữ thư mục hồ sơ (khớp đường dẫn cmdline):")
    if locks:
        for pid, name, cmd in locks:
            print(f"    - PID {pid:5d} | {name:15s} | {cmd}...")
    else:
        print("    Không có tiến trình nào đang giữ thư mục hồ sơ.")

    # 4. Cookies file status
    print(f"\n[4] Tệp cookie phiên (cookies.json):")
    if COOKIES_FILE.exists():
        try:
            data = json.loads(COOKIES_FILE.read_text(encoding="utf-8"))
            cookie_names = [c.get("name") for c in data if isinstance(c, dict)]
            has_auth = any(n in ("xf_user", "xf_session", "xf_user_session") for n in cookie_names)
            print(f"    Tệp tồn tại ({len(data)} cookie đã lưu). Có cookie đăng nhập: {'ĐÚNG' if has_auth else 'SAI'}")
        except Exception as e:
            print(f"    Tệp tồn tại nhưng không thể đọc JSON: {e}")
    else:
        print("    Chưa có tệp lưu cookie.")

    # 5. Last error from log
    last_err = get_last_error_from_log()
    print(f"\n[5] Lỗi gần nhất trong data/logs/login.log:")
    if last_err:
        print(f"    {last_err}")
    else:
        print("    Không có lỗi nào được ghi nhận.")

    print("\n" + "=" * 65)


def bring_process_windows_to_front(target_pids: Set[int]):
    """Force visible windows of target process tree to top and foreground on Windows."""
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def enum_cb(hwnd, lparam):
        if user32.IsWindowVisible(hwnd):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in target_pids:
                # SW_MAXIMIZE = 3, SW_RESTORE = 9
                user32.ShowWindow(hwnd, 3)
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
        return True

    user32.EnumWindows(WNDENUMPROC(enum_cb), 0)


def run_login():
    """Main login workflow with robust process cleanup, browser fallback, and window focus."""
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    COOKIES_FILE.parent.mkdir(parents=True, exist_ok=True)

    append_login_log("Khởi động phiên đăng nhập FUOverflow...")
    update_session(state="opening", message="Đang chuẩn bị và kiểm tra tiến trình trình duyệt...")

    # Step 1: Clean up any stale processes holding the profile
    stale = terminate_profile_locks(PROFILE_DIR)
    if stale:
        append_login_log(
            f"Đã giải phóng {len(stale)} tiến trình chạy ngầm đang giữ hồ sơ (PIDs: {[p[0] for p in stale]}).",
            level="WARNING",
        )

    # Step 2: Try browsers in order: chrome -> msedge -> chromium (None)
    from playwright.sync_api import sync_playwright

    browser_order = [
        ("chrome", "Google Chrome"),
        ("msedge", "Microsoft Edge"),
        (None, "Playwright Chromium"),
    ]

    context = None
    browser_used_name = None
    chosen_channel_key = None

    with sync_playwright() as p:
        for channel_key, display_name in browser_order:
            try:
                append_login_log(f"Thử mở trình duyệt {display_name}...")
                ctx = p.chromium.launch_persistent_context(
                    user_data_dir=str(PROFILE_DIR.resolve()),
                    channel=channel_key,
                    headless=False,
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--start-maximized",
                    ],
                    no_viewport=True,
                )
                context = ctx
                browser_used_name = display_name
                chosen_channel_key = channel_key or "chromium"
                append_login_log(f"Đã khởi động trình duyệt {display_name} thành công.")
                break
            except Exception as e:
                append_login_log(f"Không thể mở {display_name}: {e}", level="WARNING")
                continue

        if not context:
            err_msg = "Không tìm thấy hoặc không thể mở bất kỳ trình duyệt nào (Chrome, Edge, Chromium)."
            append_login_log(err_msg, level="ERROR")
            update_session(state="error", message=err_msg, error=err_msg)
            return

        # Step 3: Navigate and bring window to front
        try:
            page = context.pages[0] if context.pages else context.new_page()
            login_url = "https://fuoverflow.com/login/"
            append_login_log(f"Đang điều hướng đến trang đăng nhập: {login_url}")
            page.goto(login_url, wait_until="domcontentloaded", timeout=30000)
            page.bring_to_front()

            # Collect browser process tree PIDs to bring window to front
            all_pids: Set[int] = set()
            for proc in psutil.process_iter(["pid", "cmdline"]):
                try:
                    cmd_str = " ".join(proc.info.get("cmdline") or []).lower()
                    if str(PROFILE_DIR.resolve()).lower() in cmd_str:
                        all_pids.add(proc.info["pid"])
                except Exception:
                    pass
            bring_process_windows_to_front(all_pids)

        except Exception as e:
            err_msg = f"Lỗi khi tải trang đăng nhập FUOverflow: {e}"
            append_login_log(err_msg, level="ERROR")
            update_session(state="error", message=err_msg, browser_used=chosen_channel_key, error=str(e))
            context.close()
            return

        # Step 4: Update session state to waiting for user
        update_session(
            state="waiting_for_user",
            message=f"Đã mở cửa sổ {browser_used_name}. Vui lòng đăng nhập trên cửa sổ vừa mở.",
            browser_used=chosen_channel_key,
        )
        append_login_log(f"Chờ người dùng đăng nhập trên cửa sổ {browser_used_name} (tối đa 5 phút)...")

        # Step 5: Polling loop (max 300 seconds / 5 minutes)
        probe_url = "https://fuoverflow.com/media/q1-webp.134314/"
        timeout_seconds = 300
        start_time = time.time()
        authenticated = False

        while time.time() - start_time < timeout_seconds:
            time.sleep(2)

            # Check if cancelled by user from UI
            curr_sess = get_session_state()
            if curr_sess and curr_sess.get("state") == "cancelled":
                append_login_log("Phiên đăng nhập đã bị huỷ bởi người dùng từ giao diện.")
                context.close()
                return

            # Check if user closed the browser window
            try:
                pages_open = [pg for pg in context.pages if not pg.is_closed()]
                if not pages_open:
                    err_msg = "Người dùng đã đóng cửa sổ trình duyệt trước khi hoàn tất đăng nhập."
                    append_login_log(err_msg, level="WARNING")
                    update_session(state="error", message=err_msg, browser_used=chosen_channel_key, error=err_msg)
                    context.close()
                    return
            except Exception:
                pass

            # Check authentication status
            try:
                cookies = context.cookies()
                has_user_cookie = any(
                    c.get("name") in ("xf_user", "xf_session", "xf_user_session") and c.get("value")
                    for c in cookies
                )
                if has_user_cookie:
                    resp = context.request.get(probe_url, timeout=5000)
                    if resp.status == 200 and "/login" not in resp.url:
                        authenticated = True
                        COOKIES_FILE.write_text(
                            json.dumps(cookies, indent=2, ensure_ascii=False),
                            encoding="utf-8",
                        )
                        append_login_log("Đăng nhập thành công! Đã lưu cookie phiên đăng nhập.")
                        update_session(
                            state="authenticated",
                            message="Đã nhận diện đăng nhập thành công!",
                            browser_used=chosen_channel_key,
                        )
                        break
            except Exception as e:
                # Silently catch transient probe errors
                pass

        if not authenticated:
            err_msg = "Quá thời gian chờ đăng nhập (5 phút)."
            append_login_log(err_msg, level="ERROR")
            update_session(state="error", message=err_msg, browser_used=chosen_channel_key, error=err_msg)

        try:
            context.close()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="DocxStacked FUOverflow Login Tool")
    parser.add_argument("--diagnose", action="store_true", help="Chẩn đoán môi trường đăng nhập")
    args = parser.parse_args()

    if args.diagnose:
        run_diagnose()
    else:
        run_login()


if __name__ == "__main__":
    main()
