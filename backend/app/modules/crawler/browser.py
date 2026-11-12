import json
import os
from pathlib import Path
import sys
import time
from typing import Optional, Tuple
from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger

logger = get_logger(__name__)


def clean_stale_profile_processes(profile_dir: Path):
    """Terminate orphan processes holding the persistent browser profile directory."""
    try:
        import psutil
        target = str(profile_dir.resolve()).lower()
        curr_pid = os.getpid()
        killed = False
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                if proc.info["pid"] == curr_pid:
                    continue
                cmdline = proc.info.get("cmdline") or []
                cmd_str = " ".join(cmdline).lower()
                if target in cmd_str:
                    proc.kill()
                    killed = True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        if killed:
            time.sleep(1.0)
    except Exception as e:
        logger.debug(f"Error checking profile locks: {e}")


class AuthenticationRequiredError(Exception):
    """Raised when FUOverflow authentication is missing or expired, requiring re-login."""
    pass


class BrowserManager:
    """
    Manages Playwright Persistent Browser Context for FUOverflow.
    Ensures persistent login session in data/browser_profile,
    handles bot mitigation and session verification.
    """

    def __init__(
        self,
        profile_dir: Optional[Path] = None,
        headless: Optional[bool] = None,
        channel: Optional[str] = None,
    ):
        settings = get_settings()
        self.profile_dir = profile_dir or settings.BROWSER_PROFILE_DIR
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.headless = headless if headless is not None else settings.HEADLESS
        self.channel = channel or settings.BROWSER_CHANNEL
        if self.channel == "chromium":
            self.channel = "chrome"

        self._playwright: Optional[Playwright] = None
        self._context: Optional[BrowserContext] = None
        self._primary_page: Optional[Page] = None

    def start_context(self, headless: Optional[bool] = None) -> BrowserContext:
        """Launch persistent context."""
        if self._context is not None:
            return self._context

        is_headless = self.headless if headless is None else headless
        logger.info(f"Launching persistent browser context (headless={is_headless}, channel={self.channel})...")

        # Switch to interactive Default desktop on Windows if headed so window appears on screen
        if not is_headless and sys.platform == "win32":
            try:
                import ctypes
                user32 = ctypes.windll.user32
                hdesk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
                if hdesk:
                    user32.SetThreadDesktop(hdesk)
            except Exception as e:
                logger.debug(f"Could not switch thread desktop: {e}")

        # Ensure no residual running loop in current thread blocks Playwright Sync API
        try:
            import asyncio
            asyncio._set_running_loop(None)
        except Exception:
            pass
        try:
            import asyncio
            asyncio.set_event_loop(None)
        except Exception:
            pass

        # Clean any stale Chrome processes locking this profile directory before launch
        clean_stale_profile_processes(self.profile_dir)

        self._playwright = sync_playwright().start()

        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--start-maximized",
        ]

        try:
            self._context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                channel=self.channel,
                headless=is_headless,
                viewport={"width": 1366, "height": 850} if is_headless else None,
                no_viewport=not is_headless,
                args=launch_args,
            )
        except Exception as e:
            logger.warning(f"Failed to launch with channel={self.channel}: {e}. Retrying with default chromium...")
            self._context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=is_headless,
                args=launch_args,
            )

        # Restore saved cookies from data/auth/cookies.json if available
        cookies_file = self.profile_dir.parent / "auth" / "cookies.json"
        if cookies_file.exists():
            try:
                saved_cookies = json.loads(cookies_file.read_text(encoding="utf-8"))
                if isinstance(saved_cookies, list) and saved_cookies:
                    self._context.add_cookies(saved_cookies)
            except Exception as e:
                logger.debug(f"Error restoring cookies from cookies.json: {e}")

        self._primary_page = self._context.pages[0] if self._context.pages else self._context.new_page()
        return self._context

    def close(self) -> None:
        """Close browser context and stop playwright."""
        if self._context:
            try:
                self._context.close()
            except Exception as e:
                logger.debug(f"Context close error: {e}")
            self._context = None
            self._primary_page = None

        if self._playwright:
            try:
                self._playwright.stop()
            except Exception as e:
                logger.debug(f"Playwright stop error: {e}")
            self._playwright = None
            try:
                import asyncio
                asyncio._set_running_loop(None)
            except Exception:
                pass
            try:
                import asyncio
                asyncio.set_event_loop(None)
            except Exception:
                pass

    def has_valid_saved_cookies(self) -> bool:
        """Fast check if data/auth/cookies.json has active unexpired session without launching browser."""
        cookies_file = self.profile_dir.parent / "auth" / "cookies.json"
        if not cookies_file.exists():
            return False
        try:
            cookies = json.loads(cookies_file.read_text(encoding="utf-8"))
            if not isinstance(cookies, list) or not cookies:
                return False
            for c in cookies:
                if c.get("name") in ("xf_user", "xf_session", "xf_user_session") and c.get("value"):
                    exp = c.get("expires", 0)
                    if exp and exp > 0:
                        from datetime import datetime
                        if datetime.fromtimestamp(exp) < datetime.now():
                            return False
                    return True
        except Exception as e:
            logger.debug(f"Error checking cookies.json: {e}")
        return False

    def is_session_authenticated(self, context: Optional[BrowserContext] = None) -> bool:
        """
        Verify if current session has authenticated access to protected media.
        Tests media probe endpoint https://fuoverflow.com/media/q1-webp.134314/.
        Returns True if status is 200, False if 403 / redirect to login.
        """
        ctx = context or self._context
        if not ctx:
            return False

        try:
            # 1. Quick cookie check - fast exit if no session cookies exist
            cookies = ctx.cookies()
            has_user_cookie = any(c.get("name") in ("xf_user", "xf_user_session") and c.get("value") for c in cookies)
            if not has_user_cookie:
                return False

            # 2. Probe protected media URL only if user cookie is present
            probe_url = "https://fuoverflow.com/media/q1-webp.134314/"
            resp = ctx.request.get(probe_url, timeout=10000)
            is_valid = (resp.status == 200 and "/login" not in resp.url and 'data-logged-in="true"' in resp.text()) or (resp.status == 200 and has_user_cookie)
            if is_valid:
                # Persist valid cookies to data/auth/cookies.json for cross-session reuse
                try:
                    cookies_file = self.profile_dir.parent / "auth" / "cookies.json"
                    cookies_file.parent.mkdir(parents=True, exist_ok=True)
                    cookies_file.write_text(json.dumps(cookies, indent=2, ensure_ascii=False), encoding="utf-8")
                except Exception as e:
                    logger.debug(f"Error persisting cookies.json: {e}")
                return True
        except Exception as e:
            logger.debug(f"Session authentication check error: {e}")

        return False

    def ensure_logged_in(self, timeout_seconds: int = 30, raise_on_failure: bool = True) -> bool:
        """
        Ensure user is logged in.
        If already logged in, returns True immediately.
        If not logged in, launches browser to allow login up to timeout_seconds.
        If timeout is reached without valid session, raises AuthenticationRequiredError (or returns False if raise_on_failure=False).
        """
        # 1. Fast check cookies.json first
        if self.has_valid_saved_cookies():
            logger.info("Found valid saved session in data/auth/cookies.json.")
            try:
                ctx = self.start_context(headless=True)
                return True
            except Exception as ctx_err:
                logger.warning(f"Could not start context with saved cookies: {ctx_err}")

        # 2. Test existing session in headless mode
        ctx = self.start_context(headless=True)
        if self.is_session_authenticated(ctx):
            logger.info("Existing browser session is VALID and authenticated.")
            return True

        logger.warning(f"Session is NOT authenticated. Launching headed browser for login (timeout {timeout_seconds}s)...")
        self.close()
        time.sleep(1.5)  # Let Windows release file locks on user_data_dir before reopening

        # 2. Launch headed mode to allow login
        try:
            ctx = self.start_context(headless=False)
            page = self._primary_page or ctx.new_page()
            page.goto("https://fuoverflow.com/login/", wait_until="domcontentloaded", timeout=min(timeout_seconds * 1000, 30000))
        except Exception as e:
            logger.error(f"Failed to navigate to login page: {e}")
            self.close()
            if raise_on_failure:
                raise AuthenticationRequiredError(f"Cần đăng nhập lại: không thể mở trang đăng nhập ({e})")
            return False

        logger.info("=" * 60)
        logger.info("PLEASE COMPLETE LOGIN IN THE OPENED BROWSER WINDOW.")
        logger.info(f"Waiting for login verification (max {timeout_seconds}s)...")
        logger.info("=" * 60)

        start_time = time.time()
        while time.time() - start_time < timeout_seconds:
            time.sleep(2)
            if self.is_session_authenticated(ctx):
                logger.info("Authentication detected successfully! Session saved.")
                return True

        logger.error(f"Login check timed out after {timeout_seconds} seconds.")
        if raise_on_failure:
            raise AuthenticationRequiredError("Cần đăng nhập lại: phiên đăng nhập hết hạn hoặc chưa xác thực")
        return False


_default_browser_manager: Optional[BrowserManager] = None


def get_browser_manager() -> BrowserManager:
    global _default_browser_manager
    if _default_browser_manager is None:
        _default_browser_manager = BrowserManager()
    return _default_browser_manager

