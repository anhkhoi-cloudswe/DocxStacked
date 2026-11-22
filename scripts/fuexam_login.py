#!/usr/bin/env python3
"""
scripts/fuexam_login.py
Công cụ đăng nhập và quản lý phiên cho diễn đàn fuexam.me qua cửa sổ Chromium hiển thị (Headed).

Quy tắc bắt buộc:
1. "Đăng xuất" phải xóa: storage_state.json, mọi thư mục profile/user_data_dir của Chromium dùng cho fuexam,
   và gọi logout phía máy chủ nếu làm được (không gọi /account/*).
2. Mỗi lần đăng nhập mở Chromium MỚI, không dùng lại profile; không nạp storage_state cũ vào lúc đăng nhập.
3. Điều kiện thành công phải đồng thời:
   - Có cookie xf_user (không chấp nhận chỉ xf_session).
   - Một request trang công khai (trang chủ https://fuexam.me/) trả về html[data-logged-in="true"].
   - Tối đa chờ 5 phút, nếu không đạt thì báo hết thời gian (timeout).
4. Lưu và hiển thị tên tài khoản thật (lấy từ trang công khai), không hiện cookie hay token.
"""

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Dict, List, Optional

from bs4 import BeautifulSoup
import psutil
import requests

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
DATA_DIR = Path(os.environ.get("DOCXSTACKED_DATA_DIR", PROJECT_ROOT / "data"))
DATA_AUTH_DIR = DATA_DIR / "auth"
PROFILE_DIR = DATA_DIR / "browser_profile_fuexam"
STORAGE_STATE_FILE = DATA_AUTH_DIR / "fuexam_storage_state.json"
USER_FILE = DATA_AUTH_DIR / "fuexam_user.json"
LOG_FILE = DATA_DIR / "logs" / "fuexam_login.log"
SELF_CHECK_LOG_FILE = DATA_DIR / "logs" / "fuexam_self_check.log"
IPC_STATUS_FILE = DATA_AUTH_DIR / "fuexam_login_ipc.json"

RUN_ID: str = ""


def append_log(message: str, level: str = "INFO", stage: Optional[str] = None, is_self_check: bool = False):
    """Ghi log kèm mốc thời gian (ms), cấp độ và giai đoạn (stage). Tách riêng log login và self-check."""
    target_log = SELF_CHECK_LOG_FILE if is_self_check else LOG_FILE
    target_log.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    stage_str = f" [STAGE: {stage}]" if stage else ""
    entry = f"[{timestamp}] [{level}]{stage_str} {message}"
    try:
        with open(target_log, "a", encoding="utf-8") as f:
            f.write(entry + "\n")
            f.flush()
    except Exception:
        pass


def write_ipc_status(stage: str, state: str, message: str = "", extra: Optional[dict] = None):
    """Ghi trạng thái IPC nguyên tử để backend theo dõi với run_id và stage mốc thời gian."""
    try:
        DATA_AUTH_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "run_id": RUN_ID,
            "pid": os.getpid(),
            "stage": stage,
            "state": state,
            "message": message,
            "timestamp": time.time(),
            "iso_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        }
        if extra:
            payload.update(extra)
        temp_ipc = IPC_STATUS_FILE.with_suffix(".tmp")
        temp_ipc.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_ipc.replace(IPC_STATUS_FILE)
    except Exception as e:
        append_log(f"Lỗi ghi IPC status: {e}", level="WARNING", stage=stage)


def bring_window_to_front_windows(title_substr: str = "DocxStacked"):
    """Đưa cửa sổ có tiêu đề chứa title_substr lên trước trên Windows trong thread riêng có timeout để tránh treo."""
    if sys.platform != "win32":
        return

    def _worker():
        try:
            import ctypes
            EnumWindows = ctypes.windll.user32.EnumWindows
            EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
            GetWindowText = ctypes.windll.user32.GetWindowTextW
            GetWindowTextLength = ctypes.windll.user32.GetWindowTextLengthW
            SetForegroundWindow = ctypes.windll.user32.SetForegroundWindow
            ShowWindow = ctypes.windll.user32.ShowWindow

            def foreach_window(hwnd, lParam):
                length = GetWindowTextLength(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    GetWindowText(hwnd, buff, length + 1)
                    if title_substr.lower() in buff.value.lower():
                        ShowWindow(hwnd, 9)  # SW_RESTORE
                        SetForegroundWindow(hwnd)
                        return False
                return True

            EnumWindows(EnumWindowsProc(foreach_window), 0)
        except Exception as e:
            append_log(f"bring_window_to_front warning: {e}", level="DEBUG")

    try:
        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        t.join(timeout=1.5)
    except Exception as e:
        append_log(f"bring_window_to_front_windows error: {e}", level="DEBUG")


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
        time.sleep(0.5)
    return killed


def extract_real_username_from_html(html_text: str) -> Optional[str]:
    """Trích xuất tên tài khoản thật từ trang HTML của fuexam.me (không dùng chuỗi cố định)."""
    try:
        soup = BeautifulSoup(html_text, "html.parser")
        # 1. Selector chính xác trên thanh điều hướng XenForo của fuexam.me
        user_span = soup.select_one(".p-navgroup-link--user .p-navgroup-linkText")
        if user_span:
            txt = user_span.get_text(strip=True)
            if txt:
                return txt

        # 2. Selector tài khoản phụ
        acc_el = soup.select_one("a.p-navgroup-link--user")
        if acc_el:
            txt = acc_el.get_text(strip=True)
            if txt:
                # Loại bỏ ký tự avatar chữ cái đầu nếu bị dính
                return txt

        # 3. Quét thẻ thành viên trực tuyến / tài khoản
        for a in soup.select("a[href*='/members/']"):
            href = a.get("href", "")
            if href.rstrip("/").split("/")[-1].startswith("admin."):
                continue
            t = a.get_text(strip=True)
            if t and len(t) >= 2 and not t.endswith("is verified member."):
                return t
    except Exception as e:
        append_log(f"Lỗi phân tích username từ HTML: {e}", level="WARNING")
    return None


def verify_public_page_logged_in(cookies_dict: Dict[str, str]) -> tuple[bool, Optional[str]]:
    """
    Gửi request kiểm tra trang công khai (https://fuexam.me/) với cookie hiện tại.
    Điều kiện: Trả về status 200 và html[data-logged-in="true"].
    Trả về: (is_logged_in, real_username)
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "vi,en-US;q=0.9,en;q=0.8",
    }
    probe_url = "https://fuexam.me/"
    try:
        resp = requests.get(probe_url, cookies=cookies_dict, headers=headers, timeout=10)
        if resp.status_code == 200 and 'data-logged-in="true"' in resp.text:
            username = extract_real_username_from_html(resp.text)
            return True, username
        return False, None
    except Exception as e:
        append_log(f"Lỗi kiểm tra trang công khai: {e}", level="WARNING")
        return False, None


def check_status() -> str:
    """
    Kiểm tra trạng thái phiên fuexam.me.
    Trả về một trong 3 chuỗi: logged_in, expired, logged_out.
    """
    if not STORAGE_STATE_FILE.exists():
        return "logged_out"

    cookies_dict = {}
    try:
        state_data = json.loads(STORAGE_STATE_FILE.read_text(encoding="utf-8"))
        for c in state_data.get("cookies", []):
            cookies_dict[c["name"]] = c["value"]
    except Exception:
        return "logged_out"

    # Điều kiện bắt buộc: phải có cookie xf_user (không chấp nhận chỉ xf_session)
    if not cookies_dict.get("xf_user"):
        return "logged_out"

    is_logged_in, _ = verify_public_page_logged_in(cookies_dict)
    if is_logged_in:
        return "logged_in"
    return "expired"


def do_logout() -> bool:
    """
    Đăng xuất toàn diện:
    1. Gọi logout máy chủ fuexam.me nếu làm được (GET /logout/, lấy _xfToken, POST /logout/, KHÔNG gọi /account/*).
    2. Giải phóng tiến trình khóa profile Chromium.
    3. Xóa storage_state.json và fuexam_user.json.
    4. Xóa toàn bộ thư mục profile/user_data_dir của Chromium dùng cho fuexam.
    """
    append_log("Thực hiện đăng xuất fuexam.me...", level="INFO")

    # Kiểm tra auth_source: Nếu là extension thì KHÔNG gọi logout máy chủ
    auth_source = "headed_chromium"
    if USER_FILE.exists():
        try:
            u_data = json.loads(USER_FILE.read_text(encoding="utf-8"))
            auth_source = u_data.get("auth_source", "headed_chromium")
        except Exception:
            pass

    # 1. Gọi logout phía máy chủ nếu có cookie và KHÔNG PHẢI extension
    if auth_source != "extension" and STORAGE_STATE_FILE.exists():
        try:
            state_data = json.loads(STORAGE_STATE_FILE.read_text(encoding="utf-8"))
            cookies_dict = {c["name"]: c["value"] for c in state_data.get("cookies", [])}
            if cookies_dict.get("xf_user") or cookies_dict.get("xf_session"):
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Referer": "https://fuexam.me/",
                }
                logout_probe = requests.get("https://fuexam.me/logout/", cookies=cookies_dict, headers=headers, timeout=10)
                if logout_probe.status_code == 200:
                    soup = BeautifulSoup(logout_probe.text, "html.parser")
                    token = None
                    form = soup.find("form", action=lambda a: a and "logout" in a)
                    if form:
                        inp = form.find("input", attrs={"name": "_xfToken"})
                        if inp:
                            token = inp.get("value")
                    if not token:
                        inp = soup.find("input", attrs={"name": "_xfToken"})
                        if inp:
                            token = inp.get("value")
                    if token:
                        requests.post(
                            "https://fuexam.me/logout/",
                            data={"_xfToken": token, "_xfRedirect": "https://fuexam.me/"},
                            cookies=cookies_dict,
                            headers=headers,
                            timeout=10,
                        )
                        append_log("Đã gửi request logout lên máy chủ fuexam.me thành công.", level="INFO")
        except Exception as e:
            append_log(f"Lỗi khi gửi request logout máy chủ fuexam: {e}", level="WARNING")

    # 2. Giải phóng tiến trình khóa profile
    terminate_profile_locks(PROFILE_DIR)
    for p in DATA_DIR.glob("fuexam_*profile*"):
        if p.is_dir():
            terminate_profile_locks(p)

    # 3. Xoá tệp phiên & thông tin người dùng
    for f in (STORAGE_STATE_FILE, USER_FILE):
        try:
            if f.exists():
                f.unlink()
                append_log(f"Đã xoá tệp {f.name}.", level="INFO")
        except Exception as e:
            append_log(f"Không thể xoá {f.name}: {e}", level="WARNING")

    # 4. Xoá sạch mọi thư mục profile/user_data_dir của Chromium dùng cho fuexam
    try:
        if PROFILE_DIR.exists():
            shutil.rmtree(PROFILE_DIR, ignore_errors=True)
            append_log(f"Đã xoá thư mục profile {PROFILE_DIR.name}.", level="INFO")
    except Exception as e:
        append_log(f"Không thể xoá {PROFILE_DIR}: {e}", level="WARNING")

    for p in DATA_DIR.glob("fuexam_*profile*"):
        try:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
                append_log(f"Đã xoá thư mục profile tạm {p.name}.", level="INFO")
        except Exception:
            pass

    print("[✓] Đã đăng xuất fuexam.me thành công (đã xoá toàn bộ tệp phiên và profile Chromium).")
    return True


def run_login_headed(browser_choice: str = "chromium"):
    """
    Chạy trình duyệt Chromium MỚI (không dùng lại profile cũ, không nạp storage_state cũ).
    Ghi nhận đầy đủ mốc thời gian và giai đoạn (stages) để backend theo dõi & phát hiện điểm treo:
    - init -> before_launch -> after_launch -> after_new_page -> after_goto -> after_set_title -> after_bring_to_front -> page_loaded
    Chờ tối đa 5 phút (300 giây).
    """
    DATA_AUTH_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Stage: init
    temp_profile_dir = Path(tempfile.mkdtemp(prefix="fuexam_fresh_profile_"))
    write_ipc_status("init", "starting", f"Đã tạo profile tạm {temp_profile_dir.name}")
    append_log(f"Khởi tạo Chromium mới với profile tạm: {temp_profile_dir}", level="INFO", stage="init")

    from playwright.sync_api import sync_playwright

    channel_map = {
        "chromium": (None, "Playwright Chromium"),
        "chrome": ("chrome", "Google Chrome"),
        "msedge": ("msedge", "Microsoft Edge"),
    }
    channel_key, display_name = channel_map.get(browser_choice.lower(), (None, "Playwright Chromium"))

    login_url = "https://fuexam.me/login/"
    print("=" * 65)
    print("DOCXSTACKED - CỬA SỔ ĐĂNG NHẬP FUEXAM")
    print("=" * 65)
    print(f"Trình duyệt : {display_name}")
    print(f"Địa chỉ     : {login_url}")
    print("Hướng dẫn   : Vui lòng đăng nhập tài khoản fuexam.me trên cửa sổ Chromium vừa mở.")
    print("Lưu ý       : Không tắt cửa sổ console này. Hệ thống sẽ tự đóng khi hoàn tất.")
    print("=" * 65)

    context = None
    authenticated = False
    real_username: Optional[str] = None

    try:
        # 2. Stage: before_launch
        write_ipc_status("before_launch", "starting", f"Chuẩn bị mở trình duyệt {display_name}...")
        append_log(f"Chuẩn bị mở trình duyệt {display_name}...", level="INFO", stage="before_launch")

        with sync_playwright() as p:
            try:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(temp_profile_dir),
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
                append_log(f"Không thể mở {display_name}: {e}. Thử Playwright Chromium gốc...", level="WARNING", stage="before_launch")
                try:
                    context = p.chromium.launch_persistent_context(
                        user_data_dir=str(temp_profile_dir),
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
                    append_log(f"Lỗi nghiêm trọng: Không thể mở trình duyệt Chromium: {e2}", level="ERROR", stage="before_launch")
                    write_ipc_status("failed", "failed", f"Không thể mở Chromium: {e2}")
                    print(f"Lỗi: Không thể mở trình duyệt: {e2}")
                    sys.exit(1)

            # 3. Stage: after_launch
            write_ipc_status("after_launch", "starting", f"Persistent context {display_name} đã mở.")
            append_log(f"Đã mở persistent context ({display_name}) thành công.", level="INFO", stage="after_launch")

            # 4. Stage: after_new_page
            page = context.pages[0] if context.pages else context.new_page()
            write_ipc_status("after_new_page", "starting", "Trang web đã được tạo trong Chromium.")
            append_log("Đã khởi tạo trang Chromium.", level="INFO", stage="after_new_page")

            # 5. Stage: after_goto
            try:
                page.goto(login_url, wait_until="domcontentloaded", timeout=25000)
                write_ipc_status("after_goto", "starting", f"Đã điều hướng tới {login_url}.")
                append_log(f"Đã điều hướng tới {login_url} thành công.", level="INFO", stage="after_goto")
            except Exception as e:
                append_log(f"Lỗi điều hướng tới {login_url}: {e}", level="ERROR", stage="after_goto")
                write_ipc_status("failed", "failed", f"Lỗi tải trang đăng nhập: {e}")
                print(f"Lỗi khi điều hướng tới trang đăng nhập: {e}")
                context.close()
                sys.exit(1)

            # 6. Stage: after_set_title
            try:
                page.evaluate('''() => {
                    document.title = "DocxStacked - Đăng nhập fuexam";
                    const observer = new MutationObserver(() => {
                        if (!document.title.startsWith("DocxStacked - Đăng nhập fuexam")) {
                            document.title = "DocxStacked - Đăng nhập fuexam";
                        }
                    });
                    const titleEl = document.querySelector('title');
                    if (titleEl) {
                        observer.observe(titleEl, { childList: true, characterData: true, subtree: true });
                    }
                }''')
            except Exception as e:
                append_log(f"Lỗi đặt tiêu đề trang: {e}", level="WARNING", stage="after_set_title")
            write_ipc_status("after_set_title", "starting", "Đã thiết lập tiêu đề trang.")
            append_log("Đã thiết lập tiêu đề trang 'DocxStacked - Đăng nhập fuexam'.", level="INFO", stage="after_set_title")

            # 7. Stage: after_bring_to_front
            try:
                page.bring_to_front()
            except Exception as e:
                append_log(f"Lỗi page.bring_to_front: {e}", level="WARNING", stage="after_bring_to_front")
            bring_window_to_front_windows("DocxStacked")
            write_ipc_status("after_bring_to_front", "starting", "Đã đưa cửa sổ Chromium lên trước.")
            append_log("Đã kích hoạt đưa cửa sổ Chromium lên trước.", level="INFO", stage="after_bring_to_front")

            # 8. Stage: page_loaded -> ĐÂY LÀ ĐIỀU KIỆN CHÍNH THỨC ĐỂ BACKEND BÁO 'waiting'
            write_ipc_status("page_loaded", "waiting", "Cửa sổ Chromium đã sẵn sàng để đăng nhập.")
            append_log("Hoàn tất chuẩn bị trang. Báo hiệu IPC 'page_loaded' / 'waiting' tới backend.", level="INFO", stage="page_loaded")

            timeout_seconds = 300
            start_time = time.time()

            while time.time() - start_time < timeout_seconds:
                time.sleep(1.5)

                # Kiểm tra nếu người dùng đã chủ động tắt hết tab / cửa sổ
                try:
                    open_pages = [pg for pg in context.pages if not pg.is_closed()]
                    if not open_pages:
                        append_log("Người dùng đã đóng cửa sổ trình duyệt trước khi hoàn tất.", level="INFO", stage="closed")
                        print("\nHuỷ (Người dùng đã đóng cửa sổ trình duyệt trước khi hoàn tất).")
                        context.close()
                        sys.exit(2)
                except Exception:
                    pass

                # 1. Điều kiện A: Có cookie xf_user (không chấp nhận chỉ xf_session)
                try:
                    current_cookies = context.cookies()
                    cookies_map = {c.get("name"): c.get("value") for c in current_cookies if c.get("name")}
                    xf_user = cookies_map.get("xf_user")

                    if not xf_user or not xf_user.strip():
                        continue

                    # 2. Điều kiện B: Gửi request trang công khai https://fuexam.me/ kiểm tra html[data-logged-in="true"]
                    is_logged, parsed_username = verify_public_page_logged_in(cookies_map)
                    if is_logged:
                        authenticated = True
                        real_username = parsed_username
                        break
                except Exception as eval_err:
                    append_log(f"Lỗi kiểm tra đăng nhập: {eval_err}", level="DEBUG")

            if authenticated:
                # Lưu storage state
                context.storage_state(path=str(STORAGE_STATE_FILE))
                set_owner_only_permissions(STORAGE_STATE_FILE)

                # Lưu thông tin tài khoản thật
                user_info = {
                    "username": real_username or "Thành viên fuexam",
                    "logged_in_at": datetime.now().isoformat(),
                    "auth_source": "headed_chromium",
                }
                USER_FILE.write_text(json.dumps(user_info, indent=2, ensure_ascii=False), encoding="utf-8")
                set_owner_only_permissions(USER_FILE)

                append_log(f"Đăng nhập fuexam.me thành công! Tài khoản: '{real_username}'", level="INFO", stage="authenticated")
                write_ipc_status("authenticated", "success", f"Đăng nhập thành công ({real_username})")
                print("\n" + "=" * 65)
                print(f"[✓] ĐĂNG NHẬP THÀNH CÔNG! Tài khoản: {real_username}")
                print(f"    Tệp phiên: {STORAGE_STATE_FILE}")
                print("=" * 65)
                context.close()
                sys.exit(0)
            else:
                append_log("Quá thời hạn chờ 5 phút mà chưa hoàn tất đăng nhập fuexam.me.", level="WARNING", stage="timeout")
                write_ipc_status("timeout", "timeout", "Hết thời gian chờ đăng nhập (5 phút).")
                print("\n[!] Hết thời gian chờ (5 phút) mà chưa hoàn tất đăng nhập.")
                context.close()
                sys.exit(1)

    finally:
        # Dọn dẹp profile tạm của phiên này
        terminate_profile_locks(temp_profile_dir)
        try:
            if temp_profile_dir.exists():
                shutil.rmtree(temp_profile_dir, ignore_errors=True)
        except Exception:
            pass
        try:
            if IPC_STATUS_FILE.exists():
                IPC_STATUS_FILE.unlink()
        except Exception:
            pass


def run_self_check(browser_choice: str = "chromium") -> dict:
    """
    Tự kiểm tra trình duyệt Chromium:
    Mở Chromium tới about:blank trong 3 giây rồi đóng, in và trả về kết quả.
    Ghi log riêng vào fuexam_self_check.log.
    """
    DATA_AUTH_DIR.mkdir(parents=True, exist_ok=True)
    temp_profile_dir = Path(tempfile.mkdtemp(prefix="fuexam_selfcheck_"))
    append_log("Khởi động Chromium self-check...", level="INFO", is_self_check=True)

    channel_map = {
        "chromium": (None, "Playwright Chromium"),
        "chrome": ("chrome", "Google Chrome"),
        "msedge": ("msedge", "Microsoft Edge"),
    }
    channel_key, display_name = channel_map.get(browser_choice.lower(), (None, "Playwright Chromium"))

    result = {
        "success": False,
        "browser": display_name,
        "executable_path": "",
        "message": "",
    }

    from playwright.sync_api import sync_playwright
    try:
        with sync_playwright() as p:
            try:
                exec_path = p.chromium.executable_path or ""
            except Exception:
                exec_path = ""
            result["executable_path"] = exec_path

            context = p.chromium.launch_persistent_context(
                user_data_dir=str(temp_profile_dir),
                channel=channel_key,
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--window-size=900,650",
                ],
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.goto("about:blank")
            try:
                page.evaluate('() => { document.title = "DocxStacked - Kiểm tra Chromium"; }')
            except Exception:
                pass
            page.bring_to_front()
            bring_window_to_front_windows("DocxStacked")

            time.sleep(3)
            context.close()
            result["success"] = True
            result["message"] = f"Đã mở {display_name} tới about:blank trong 3 giây và đóng thành công."
            append_log(f"Chromium self-check thành công ({exec_path})", level="INFO", is_self_check=True)
    except Exception as e:
        result["success"] = False
        result["message"] = f"Lỗi khi mở Chromium: {e}"
        append_log(f"Chromium self-check thất bại: {e}", level="ERROR", is_self_check=True)
    finally:
        terminate_profile_locks(temp_profile_dir)
        try:
            if temp_profile_dir.exists():
                shutil.rmtree(temp_profile_dir, ignore_errors=True)
        except Exception:
            pass

    print("=" * 65)
    print("DOCXSTACKED - KIỂM TRA CHROMIUM (SELF-CHECK)")
    print("=" * 65)
    print(f"Trình duyệt          : {result['browser']}")
    print(f"Đường dẫn thực thi   : {result['executable_path'] or 'Mặc định hệ thống'}")
    print(f"Kết quả mở           : {'Thành công' if result['success'] else 'Thất bại'}")
    print(f"Chi tiết             : {result['message']}")
    print("=" * 65)
    return result


def main():
    global RUN_ID
    parser = argparse.ArgumentParser(description="Công cụ đăng nhập và quản lý phiên fuexam.me")
    parser.add_argument(
        "--browser",
        choices=["chromium", "chrome", "msedge"],
        default="chromium",
        help="Chọn loại trình duyệt cho cửa sổ đăng nhập (mặc định: chromium)",
    )
    parser.add_argument("--run-id", type=str, default="", help="Mã phiên duy nhất từ backend để đối soát IPC")
    parser.add_argument("--status", action="store_true", help="Kiểm tra trạng thái phiên: logged_in / expired / logged_out")
    parser.add_argument("--logout", action="store_true", help="Đăng xuất, xoá toàn bộ phiên và profile Chromium")
    parser.add_argument("--self-check", action="store_true", help="Mở Chromium tới about:blank 3 giây rồi đóng, kiểm tra môi trường")
    args = parser.parse_args()

    RUN_ID = args.run_id or f"local_{int(time.time())}"

    if args.status:
        st = check_status()
        print(st)
    elif args.logout:
        do_logout()
    elif args.self_check:
        res = run_self_check(browser_choice=args.browser)
        sys.exit(0 if res.get("success") else 1)
    else:
        run_login_headed(browser_choice=args.browser)


if __name__ == "__main__":
    main()
