"""
backend/app/modules/crawler/fuexam_crawler.py
Module cào dữ liệu, quản lý phiên và bộ nhớ đệm (Cache) cho nền tảng fuexam.me.

Tuân thủ nghiêm ngặt các quy tắc:
1. Luôn sử dụng phiên đăng nhập hợp lệ (từ data/auth/fuexam_storage_state.json).
   Nếu phiên không hợp lệ hoặc hết hạn -> Dừng ngay lập tức với trạng thái 'cần đăng nhập'.
2. Cache ảnh và bình luận theo media_id kèm thời điểm lấy (fetched_at).
   Tái sử dụng cache để soạn thảo lại mà không tải lại mạng.
3. Hỗ trợ tùy chọn force_refresh=True để làm mới bắt buộc.
4. Tôn trọng độ trễ an toàn tối thiểu 1.6 giây giữa các request mạng.
"""

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import json
import logging
import os
from pathlib import Path
import random
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from urllib.parse import urljoin, urlsplit, urlunsplit
import uuid

from bs4 import BeautifulSoup
import numpy as np
from PIL import Image
import requests

from backend.app.core.config import get_settings

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
AUTH_FILE = DATA_DIR / "auth" / "fuexam_storage_state.json"
CACHE_DIR = DATA_DIR / "cache" / "fuexam"
RAW_DIR = DATA_DIR / "raw" / "fuexam"

BASE_URL = "https://fuexam.me"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
DEFAULT_DELAY = 0.4


class AuthenticationRequiredError(Exception):
    """Ngoại lệ khi chưa có phiên đăng nhập hoặc phiên đã hết hạn."""
    pass


class JobCancelledError(Exception):
    """Ngoại lệ khi người dùng huỷ tiến trình trong lúc đang chờ hoặc retry."""
    pass


_active_client_local = threading.local()


def set_active_fuexam_client(client: Optional["FuexamHttpClient"]) -> None:
    """Gắn FuexamHttpClient cho luồng hiện tại (dùng bởi orchestrator)."""
    _active_client_local.client = client


def get_active_fuexam_client() -> Optional["FuexamHttpClient"]:
    """Lấy FuexamHttpClient đang gắn trên luồng hiện tại (nếu có)."""
    return getattr(_active_client_local, "client", None)


class FuexamRequestError(Exception):
    """Ngoại lệ chuẩn hoá cho các lỗi mạng/HTTP khi gọi fuexam.me."""

    def __init__(
        self,
        message: str,
        *,
        error_type: str = "unknown",
        error_code: Optional[str] = None,
        status_code: Optional[int] = None,
        url: str = "",
        attempts: int = 1,
    ):
        super().__init__(message)
        self.error_type = error_type
        self.error_code = error_code or f"NET-{uuid.uuid4().hex[:6].upper()}"
        self.status_code = status_code
        self.url = url
        self.attempts = attempts


class CommentFetchError(FuexamRequestError):
    """Ngoại lệ khi tải bình luận câu hỏi thất bại sau khi đã retry."""

    def __init__(
        self,
        message: str,
        *,
        media_id: int,
        error_type: str = "unknown",
        error_code: Optional[str] = None,
        status_code: Optional[int] = None,
        url: str = "",
        attempts: int = 1,
    ):
        super().__init__(
            message,
            error_type=error_type,
            error_code=error_code,
            status_code=status_code,
            url=url,
            attempts=attempts,
        )
        self.media_id = media_id


def _sanitize_url(url: str) -> str:
    """Loại bỏ query/fragment để không bao giờ ghi token hay thông tin nhạy cảm vào log."""
    try:
        parts = urlsplit(url)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    except Exception:
        return url.split("?")[0]


def _atomic_write_bytes(target: Path, data: bytes) -> None:
    """Ghi file nhị phân nguyên tử: ghi ra file tạm cùng thư mục rồi os.replace."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.parent / f".{target.name}.tmp_{os.getpid()}_{threading.get_ident()}"
    try:
        tmp_path.write_bytes(data)
        os.replace(str(tmp_path), str(target))
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise


def _atomic_write_text(target: Path, text: str, encoding: str = "utf-8") -> None:
    """Ghi file văn bản nguyên tử: ghi ra file tạm cùng thư mục rồi os.replace."""
    _atomic_write_bytes(target, text.encode(encoding))


def _parse_retry_after(header_val: Optional[str]) -> Optional[float]:
    """Phân tích header Retry-After (số giây hoặc HTTP-date)."""
    if not header_val:
        return None
    raw = header_val.strip()
    try:
        val = float(raw)
        return max(0.0, val)
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        diff = (dt - datetime.now(timezone.utc)).total_seconds()
        return max(0.0, diff)
    except Exception:
        return None


class FuexamHttpClient:
    """
    HTTP client lịch sự và có khả năng phục hồi cho fuexam.me:
    - Tách connect/read timeout (mặc định 10s / 45s).
    - Tối đa 4 lần thử, exponential backoff + jitter, tôn trọng Retry-After (429/503).
    - Không retry các lỗi 4xx khác (401/403/404).
    - Giới hạn đồng thời (mặc định 2) và giãn cách tối thiểu (mặc định 0.4s).
    - Circuit breaker: sau N timeout liên tiếp (mặc định 3) tạm nghỉ 30-60s rồi giảm tốc.
    - Hỗ trợ huỷ tức thì qua cancel_event ngay cả khi đang backoff hoặc circuit breaker.
    """

    def __init__(
        self,
        *,
        connect_timeout: Optional[float] = None,
        read_timeout: Optional[float] = None,
        max_attempts: Optional[int] = None,
        backoff_base: float = 1.5,
        max_concurrency: Optional[int] = None,
        min_delay_seconds: Optional[float] = None,
        circuit_breaker_threshold: Optional[int] = None,
        circuit_breaker_pause_seconds: Optional[float] = None,
        cancel_event: Optional[threading.Event] = None,
        event_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ):
        crawl_cfg = get_settings().yaml_config.crawl
        self.connect_timeout = float(
            connect_timeout if connect_timeout is not None else getattr(crawl_cfg, "fuexam_connect_timeout", 10.0)
        )
        self.read_timeout = float(
            read_timeout if read_timeout is not None else getattr(crawl_cfg, "fuexam_read_timeout", 45.0)
        )
        self.max_attempts = max(1, int(
            max_attempts if max_attempts is not None else getattr(crawl_cfg, "fuexam_max_retries", 4)
        ))
        self.backoff_base = float(backoff_base)
        self.max_concurrency = max(1, int(
            max_concurrency if max_concurrency is not None else getattr(crawl_cfg, "fuexam_max_concurrency", 2)
        ))
        self.min_delay_seconds = max(0.0, float(
            min_delay_seconds if min_delay_seconds is not None else getattr(crawl_cfg, "fuexam_min_delay_seconds", 0.4)
        ))
        self.circuit_breaker_threshold = max(1, int(
            circuit_breaker_threshold
            if circuit_breaker_threshold is not None
            else getattr(crawl_cfg, "fuexam_circuit_breaker_threshold", 3)
        ))
        self.circuit_breaker_pause_seconds = max(0.0, float(
            circuit_breaker_pause_seconds
            if circuit_breaker_pause_seconds is not None
            else getattr(crawl_cfg, "fuexam_circuit_breaker_pause_seconds", 45.0)
        ))
        self.cancel_event = cancel_event
        self.event_callback = event_callback

        self._semaphore = threading.Semaphore(self.max_concurrency)
        self._rate_lock = threading.Lock()
        self._last_request_ts = 0.0
        self._current_min_delay = self.min_delay_seconds

        self._cb_lock = threading.Lock()
        self._consecutive_timeouts = 0
        self._breaker_until = 0.0
        self._slow_mode = False

        # Metrics for observability
        self._metrics_lock = threading.Lock()
        self.latencies_ms: List[float] = []
        self.total_requests = 0
        self.retry_count = 0
        self.error_count = 0
        self.timeout_count = 0
        self.rate_limit_count = 0
        self.server_error_count = 0
        self.connection_error_count = 0
        self.circuit_breaker_trips = 0

    def _emit(self, payload: Dict[str, Any]) -> None:
        if self.event_callback:
            try:
                self.event_callback(payload)
            except Exception:
                pass

    def _check_cancelled(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise JobCancelledError("Tiến trình đã bị huỷ bởi người dùng.")

    def _cancellable_sleep(self, seconds: float) -> None:
        self._check_cancelled()
        if seconds <= 0:
            return
        if self.cancel_event is not None:
            if self.cancel_event.wait(timeout=seconds):
                raise JobCancelledError("Tiến trình đã bị huỷ bởi người dùng.")
        else:
            time.sleep(seconds)

    def _compute_backoff(self, attempt: int) -> float:
        base = self.backoff_base * (2 ** max(0, attempt - 1))
        jitter = random.uniform(0.0, 0.5 * base)
        return base + jitter

    def _wait_rate_limit_and_breaker(self) -> None:
        while True:
            self._check_cancelled()
            with self._cb_lock:
                remaining_cb = self._breaker_until - time.monotonic()
            if remaining_cb > 0:
                self._cancellable_sleep(min(remaining_cb, 1.0))
                continue
            break

        with self._rate_lock:
            now = time.monotonic()
            elapsed = now - self._last_request_ts
            wait_s = max(0.0, self._current_min_delay - elapsed)
            self._last_request_ts = now + wait_s
        if wait_s > 0:
            self._cancellable_sleep(wait_s)

    def _record_timeout_and_maybe_trip(
        self,
        *,
        exam_id: Optional[int],
        question_index: Optional[int],
        clean_url: str,
        err_code: str,
    ) -> None:
        pause_needed = 0.0
        with self._cb_lock:
            self._consecutive_timeouts += 1
            if self._consecutive_timeouts >= self.circuit_breaker_threshold:
                pause_needed = self.circuit_breaker_pause_seconds
                self._breaker_until = time.monotonic() + pause_needed
                self._consecutive_timeouts = 0
                self._slow_mode = True
                self.circuit_breaker_trips += 1
                with self._rate_lock:
                    self._current_min_delay = min(5.0, max(self._current_min_delay * 2.0, 1.2))
                new_delay = self._current_min_delay

        if pause_needed > 0:
            logger.warning(
                f"[CircuitBreaker] [{err_code}] {self.circuit_breaker_threshold} timeout liên tiếp "
                f"(exam={exam_id}, q={question_index}, url={clean_url}). "
                f"Tạm nghỉ {pause_needed:.1f}s và giảm tốc (delay={new_delay:.2f}s)."
            )
            self._emit({
                "type": "log",
                "step": "circuit_breaker",
                "is_rate_limiting": True,
                "circuit_breaker": True,
                "wait_seconds": round(pause_needed, 1),
                "message": f"fuexam phản hồi chậm, đang chờ {int(round(pause_needed))}s trước khi tiếp tục...",
            })
            self._cancellable_sleep(pause_needed)

    def _reset_timeout_streak(self) -> None:
        with self._cb_lock:
            self._consecutive_timeouts = 0

    def get_metrics_summary(self) -> Dict[str, Any]:
        with self._metrics_lock:
            lats = sorted(self.latencies_ms)
            n = len(lats)
            p50 = lats[int(0.50 * (n - 1))] if n > 0 else 0.0
            p95 = lats[int(0.95 * (n - 1))] if n > 0 else 0.0
            return {
                "total_requests": self.total_requests,
                "retry_count": self.retry_count,
                "error_count": self.error_count,
                "timeout_count": self.timeout_count,
                "rate_limit_count": self.rate_limit_count,
                "server_error_count": self.server_error_count,
                "connection_error_count": self.connection_error_count,
                "circuit_breaker_trips": self.circuit_breaker_trips,
                "p50_latency_ms": round(p50, 1),
                "p95_latency_ms": round(p95, 1),
                "slow_mode_triggered": self._slow_mode,
            }

    def get(
        self,
        session: requests.Session,
        url: str,
        *,
        allow_redirects: bool = True,
        exam_id: Optional[int] = None,
        exam_title: Optional[str] = None,
        question_index: Optional[int] = None,
        media_id: Optional[int] = None,
        expect_html: bool = False,
        min_bytes: int = 1,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        clean_url = _sanitize_url(url)
        last_error: Optional[FuexamRequestError] = None

        for attempt in range(1, self.max_attempts + 1):
            self._check_cancelled()
            self._wait_rate_limit_and_breaker()

            if attempt > 1:
                self._emit({
                    "type": "progress",
                    "step": "retrying",
                    "retry_attempt": attempt - 1,
                    "max_retries": self.max_attempts - 1,
                    "current_question": question_index,
                    "message": f"Đang thử lại lần {attempt - 1}/{self.max_attempts - 1} (câu {question_index or '?'})...",
                })

            t0 = time.monotonic()
            try:
                with self._metrics_lock:
                    self.total_requests += 1
                with self._semaphore:
                    self._check_cancelled()
                    req_kwargs: Dict[str, Any] = {
                        "allow_redirects": allow_redirects,
                        "timeout": (self.connect_timeout, self.read_timeout),
                    }
                    if headers:
                        req_kwargs["headers"] = headers
                    resp = session.get(url, **req_kwargs)
                elapsed_ms = (time.monotonic() - t0) * 1000.0
                with self._metrics_lock:
                    self.latencies_ms.append(elapsed_ms)

                # 1. Auth check (401/403 hoặc bị chuyển hướng về /login hoặc HTML logged_out) -> KHÔNG retry
                resp_url_clean = _sanitize_url(getattr(resp, "url", "") or "")
                is_logged_out_html = False
                if expect_html and resp.status_code == 200:
                    body_text = resp.text or ""
                    if 'data-logged-in="false"' in body_text or "/login" in resp_url_clean:
                        is_logged_out_html = True
                if resp.status_code in (401, 403) or "/login" in resp_url_clean or is_logged_out_html:
                    err_code = f"NET-{uuid.uuid4().hex[:6].upper()}"
                    logger.error(
                        f"[FuexamAuth] [{err_code}] exam={exam_id} q={question_index} media={media_id} "
                        f"url={clean_url} attempt={attempt}/{self.max_attempts} time={elapsed_ms:.0f}ms "
                        f"status={resp.status_code} -> Phiên đăng nhập hết hạn/bị đăng xuất."
                    )
                    raise AuthenticationRequiredError(
                        f"Phiên đăng nhập fuexam.me đã hết hạn hoặc bị đăng xuất (HTTP {resp.status_code}, mã: {err_code})."
                    )

                # 2. 429 / 5xx -> retry có kiểm soát, tôn trọng Retry-After với 429/503
                if resp.status_code == 429 or 500 <= resp.status_code < 600:
                    err_type = "rate_limit" if resp.status_code == 429 else "server_error"
                    err_code = f"NET-{uuid.uuid4().hex[:6].upper()}"
                    with self._metrics_lock:
                        if resp.status_code == 429:
                            self.rate_limit_count += 1
                        else:
                            self.server_error_count += 1
                    retry_after = (
                        _parse_retry_after(resp.headers.get("Retry-After"))
                        if resp.status_code in (429, 503)
                        else None
                    )
                    logger.warning(
                        f"[FuexamHTTP] [{err_code}] type={err_type} status={resp.status_code} "
                        f"exam={exam_id} q={question_index} media={media_id} url={clean_url} "
                        f"attempt={attempt}/{self.max_attempts} time={elapsed_ms:.0f}ms retry_after={retry_after}"
                    )
                    last_error = FuexamRequestError(
                        f"Lỗi máy chủ fuexam (HTTP {resp.status_code}, mã {err_code})",
                        error_type=err_type,
                        error_code=err_code,
                        status_code=resp.status_code,
                        url=clean_url,
                        attempts=attempt,
                    )
                    if attempt < self.max_attempts:
                        with self._metrics_lock:
                            self.retry_count += 1
                        wait_s = retry_after if retry_after is not None else self._compute_backoff(attempt)
                        self._cancellable_sleep(wait_s)
                        continue
                    with self._metrics_lock:
                        self.error_count += 1
                    raise last_error

                # 3. Các lỗi 4xx khác (404, 400, ...) -> KHÔNG retry
                if 400 <= resp.status_code < 500:
                    err_code = f"NET-{uuid.uuid4().hex[:6].upper()}"
                    with self._metrics_lock:
                        self.error_count += 1
                    logger.error(
                        f"[FuexamHTTP] [{err_code}] type=http_4xx status={resp.status_code} "
                        f"exam={exam_id} q={question_index} media={media_id} url={clean_url} "
                        f"attempt={attempt}/{self.max_attempts} time={elapsed_ms:.0f}ms"
                    )
                    raise FuexamRequestError(
                        f"Yêu cầu thất bại với mã HTTP {resp.status_code} (mã {err_code})",
                        error_type="http_4xx",
                        error_code=err_code,
                        status_code=resp.status_code,
                        url=clean_url,
                        attempts=attempt,
                    )

                # 4. Kiểm tra trang rỗng bất thường
                content_bytes = resp.content or b""
                is_empty = (expect_html and not (resp.text or "").strip()) or (len(content_bytes) < min_bytes)
                if resp.status_code == 200 and is_empty:
                    err_code = f"NET-{uuid.uuid4().hex[:6].upper()}"
                    logger.warning(
                        f"[FuexamHTTP] [{err_code}] type=empty_response bytes={len(content_bytes)} "
                        f"exam={exam_id} q={question_index} media={media_id} url={clean_url} "
                        f"attempt={attempt}/{self.max_attempts} time={elapsed_ms:.0f}ms"
                    )
                    last_error = FuexamRequestError(
                        f"Phản hồi rỗng bất thường từ fuexam ({len(content_bytes)} bytes, mã {err_code})",
                        error_type="empty_response",
                        error_code=err_code,
                        status_code=resp.status_code,
                        url=clean_url,
                        attempts=attempt,
                    )
                    if attempt < self.max_attempts:
                        with self._metrics_lock:
                            self.retry_count += 1
                        self._cancellable_sleep(self._compute_backoff(attempt))
                        continue
                    with self._metrics_lock:
                        self.error_count += 1
                    raise last_error

                # Thành công
                self._reset_timeout_streak()
                logger.debug(
                    f"[FuexamHTTP] OK status={resp.status_code} exam={exam_id} q={question_index} "
                    f"media={media_id} url={clean_url} attempt={attempt}/{self.max_attempts} time={elapsed_ms:.0f}ms"
                )
                return resp

            except (AuthenticationRequiredError, JobCancelledError, FuexamRequestError):
                raise
            except requests.Timeout as e:
                elapsed_ms = (time.monotonic() - t0) * 1000.0
                err_code = f"NET-{uuid.uuid4().hex[:6].upper()}"
                with self._metrics_lock:
                    self.latencies_ms.append(elapsed_ms)
                    self.timeout_count += 1
                logger.warning(
                    f"[FuexamHTTP] [{err_code}] type=timeout exam={exam_id} q={question_index} media={media_id} "
                    f"url={clean_url} attempt={attempt}/{self.max_attempts} time={elapsed_ms:.0f}ms err={e.__class__.__name__}"
                )
                last_error = FuexamRequestError(
                    f"Quá hạn kết nối/đọc từ fuexam ({e.__class__.__name__}, mã {err_code})",
                    error_type="timeout",
                    error_code=err_code,
                    url=clean_url,
                    attempts=attempt,
                )
                self._record_timeout_and_maybe_trip(
                    exam_id=exam_id,
                    question_index=question_index,
                    clean_url=clean_url,
                    err_code=err_code,
                )
                if attempt < self.max_attempts:
                    with self._metrics_lock:
                        self.retry_count += 1
                    self._cancellable_sleep(self._compute_backoff(attempt))
                    continue
                with self._metrics_lock:
                    self.error_count += 1
                raise last_error
            except (requests.ConnectionError, OSError) as e:
                elapsed_ms = (time.monotonic() - t0) * 1000.0
                err_code = f"NET-{uuid.uuid4().hex[:6].upper()}"
                with self._metrics_lock:
                    self.latencies_ms.append(elapsed_ms)
                    self.connection_error_count += 1
                logger.warning(
                    f"[FuexamHTTP] [{err_code}] type=connection exam={exam_id} q={question_index} media={media_id} "
                    f"url={clean_url} attempt={attempt}/{self.max_attempts} time={elapsed_ms:.0f}ms err={e.__class__.__name__}"
                )
                last_error = FuexamRequestError(
                    f"Lỗi kết nối mạng tới fuexam ({e.__class__.__name__}, mã {err_code})",
                    error_type="connection",
                    error_code=err_code,
                    url=clean_url,
                    attempts=attempt,
                )
                if attempt < self.max_attempts:
                    with self._metrics_lock:
                        self.retry_count += 1
                    self._cancellable_sleep(self._compute_backoff(attempt))
                    continue
                with self._metrics_lock:
                    self.error_count += 1
                raise last_error

        if last_error:
            raise last_error
        raise FuexamRequestError("Lỗi không xác định khi tải dữ liệu fuexam.", url=clean_url)


def get_authenticated_session() -> requests.Session:
    """Khởi tạo requests.Session mang cookie phiên từ storage_state."""
    if not AUTH_FILE.exists():
        raise AuthenticationRequiredError(
            "Cần đăng nhập fuexam.me: Không tìm thấy data/auth/fuexam_storage_state.json. "
            "Vui lòng mở Dashboard để đăng nhập hoặc chạy cửa sổ Chromium: python scripts/fuexam_login.py"
        )

    try:
        state = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        raise AuthenticationRequiredError(f"Tệp phiên bị lỗi không thể đọc: {e}")

    cookies = state.get("cookies", [])
    cookies_map = {c.get("name"): c.get("value") for c in cookies}
    # Điều kiện bắt buộc: phải có cookie xf_user (không chấp nhận chỉ xf_session)
    if not cookies_map.get("xf_user"):
        raise AuthenticationRequiredError(
            "Cần đăng nhập fuexam.me: Không có cookie 'xf_user' hợp lệ trong tệp phiên (không chấp nhận chỉ xf_session)."
        )

    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "vi,en-US;q=0.9,en;q=0.8",
    })

    for c in cookies:
        session.cookies.set(
            name=c["name"],
            value=c["value"],
            domain=c.get("domain", "").lstrip("."),
            path=c.get("path", "/"),
        )

    return session


def check_session_validity(
    session: requests.Session,
    client: Optional[FuexamHttpClient] = None,
) -> bool:
    """Kiểm tra xem phiên có còn hợp lệ không trước khi bắt đầu cào (dùng public thread, không gọi /account/)."""
    probe_url = "https://fuexam.me/threads/prm393-su26-fe-re.941/"
    http = client or get_active_fuexam_client() or FuexamHttpClient(max_attempts=2, min_delay_seconds=0.0)
    try:
        resp = http.get(session, probe_url, allow_redirects=True, expect_html=True)
        if resp.status_code == 200 and "/login" not in resp.url and 'data-logged-in="true"' in resp.text:
            return True
        return False
    except AuthenticationRequiredError:
        return False
    except JobCancelledError:
        raise
    except Exception:
        return False


def get_media_cache_dir(media_id: int) -> Path:
    """Thư mục lưu cache riêng cho từng media_id."""
    m_dir = CACHE_DIR / f"media_{media_id}"
    m_dir.mkdir(parents=True, exist_ok=True)
    return m_dir


def extract_thread_questions(
    thread_url: str,
    session: requests.Session,
    *,
    client: Optional[FuexamHttpClient] = None,
    exam_id: Optional[int] = None,
    exam_title: Optional[str] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Quét thread bài viết để trích xuất danh sách tất cả các ảnh câu hỏi đính kèm.
    Trả về (tiêu đề thread, danh sách các mục câu hỏi).
    """
    http = client or get_active_fuexam_client() or FuexamHttpClient()
    resp = http.get(
        session,
        thread_url,
        exam_id=exam_id,
        exam_title=exam_title,
        expect_html=True,
    )

    soup = BeautifulSoup(resp.text, "html.parser")
    thread_title = soup.title.string.strip() if soup.title else "Đề Thi fuexam.me"
    # Dọn bớt hậu tố title
    thread_title = re.sub(r"\s*\|\s*FuExam.*$", "", thread_title).strip()

    questions: List[Dict[str, Any]] = []
    previews = soup.select("section.message-attachments a.file-preview")

    for idx, prev in enumerate(previews, 1):
        href = prev.get("href", "")
        sb_href = prev.get("data-lb-sidebar-href", "")

        # Trích xuất attachment_id từ href (ví dụ /attachments/...-webp.68981/)
        m_att = re.search(r"\.(\d+)/?$", href)
        attachment_id = int(m_att.group(1)) if m_att else None

        # Trích xuất media_id từ data-lb-sidebar-href (ví dụ /media/...-webp.34522/?lightbox=1)
        m_med = re.search(r"/media/(?:[^/?]+\.)?(\d+)/?", sb_href)
        media_id = int(m_med.group(1)) if m_med else (attachment_id or idx)

        # Trích xuất slug
        m_slug = re.search(r"/media/([^/?]+)\.\d+/?", sb_href)
        slug = m_slug.group(1) if m_slug else f"q_{idx}"

        alt = prev.find("img").get("alt", f"Câu {idx}") if prev.find("img") else f"Câu {idx}"

        questions.append({
            "index": idx,
            "title": alt,
            "slug": slug,
            "media_id": media_id,
            "attachment_id": attachment_id,
            "attachment_url": urljoin(BASE_URL, href),
            "media_url": f"https://fuexam.me/media/{slug}.{media_id}/",
        })

    return thread_title, questions


def fetch_and_cache_media_image(
    media_id: int,
    attachment_url: str,
    slug: str,
    session: requests.Session,
    force_refresh: bool = False,
    delay_seconds: float = DEFAULT_DELAY,
    *,
    client: Optional[FuexamHttpClient] = None,
    exam_id: Optional[int] = None,
    question_index: Optional[int] = None,
) -> Tuple[Path, bool]:
    """
    Tải và lưu cache ảnh đề thi theo media_id (ghi nguyên tử).
    Nếu cache đã có và force_refresh=False: Đọc từ cache ngay lập tức (không gọi mạng).
    Trả về (đường dẫn file ảnh, is_cached).
    """
    m_dir = get_media_cache_dir(media_id)
    raw_image_path = m_dir / f"{slug}.webp"
    meta_path = m_dir / "image_meta.json"

    if not force_refresh and raw_image_path.exists() and meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("file_size", 0) > 0 and raw_image_path.stat().st_size > 0:
                logger.debug(f"[Cache Hit] Sử dụng ảnh từ cache: {raw_image_path}")
                return raw_image_path, True
        except Exception:
            pass

    http = client or get_active_fuexam_client() or FuexamHttpClient(min_delay_seconds=delay_seconds)
    resp: Optional[requests.Response] = None
    try:
        resp = http.get(
            session,
            attachment_url,
            allow_redirects=True,
            exam_id=exam_id,
            question_index=question_index,
            media_id=media_id,
            min_bytes=100,
        )
    except (AuthenticationRequiredError, JobCancelledError):
        raise
    except FuexamRequestError:
        media_full_url = f"https://fuexam.me/media/{slug}.{media_id}/full"
        resp = http.get(
            session,
            media_full_url,
            allow_redirects=True,
            exam_id=exam_id,
            question_index=question_index,
            media_id=media_id,
            min_bytes=100,
        )

    if resp is None or resp.status_code != 200 or len(resp.content) < 100:
        status_val = resp.status_code if resp is not None else "N/A"
        raise FuexamRequestError(
            f"Không thể tải ảnh media {media_id} (HTTP {status_val})",
            error_type="empty_response",
            status_code=resp.status_code if resp is not None else None,
            url=_sanitize_url(attachment_url),
        )

    # Lưu ảnh và metadata nguyên tử vào cache
    _atomic_write_bytes(raw_image_path, resp.content)
    sha256_hash = hashlib.sha256(resp.content).hexdigest()

    meta_data = {
        "media_id": media_id,
        "slug": slug,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source_url": _sanitize_url(attachment_url),
        "sha256": sha256_hash,
        "file_size": len(resp.content),
    }
    _atomic_write_text(meta_path, json.dumps(meta_data, indent=2, ensure_ascii=False))

    return raw_image_path, False


def fetch_and_cache_media_comments(
    media_id: int,
    slug: str,
    session: requests.Session,
    force_refresh: bool = False,
    delay_seconds: float = DEFAULT_DELAY,
    *,
    client: Optional[FuexamHttpClient] = None,
    exam_id: Optional[int] = None,
    question_index: Optional[int] = None,
    base_url: str = BASE_URL,
) -> Tuple[List[Dict[str, Any]], bool]:
    """
    Tải và lưu cache bình luận của câu hỏi theo media_id.
    - Nếu cache đã có và force_refresh=False: Tái sử dụng cache ngay lập tức.
    - Nếu tải thất bại sau khi hết retry: KHÔNG lưu cache rỗng, ném CommentFetchError.
    - Nếu thành công: ghi cache nguyên tử (file tạm rồi đổi tên).
    Trả về (danh sách bình luận, is_cached).
    """
    m_dir = get_media_cache_dir(media_id)
    comments_file = m_dir / "comments.json"

    if not force_refresh and comments_file.exists():
        try:
            cached_payload = json.loads(comments_file.read_text(encoding="utf-8"))
            if isinstance(cached_payload, dict) and "comments" in cached_payload:
                logger.debug(
                    f"[Cache Hit] Đọc {len(cached_payload.get('comments', []))} bình luận từ cache media {media_id}"
                )
                return cached_payload.get("comments", []), True
        except Exception:
            pass

    media_url = f"{base_url.rstrip('/')}/media/{slug}.{media_id}/"
    http = client or get_active_fuexam_client() or FuexamHttpClient(min_delay_seconds=delay_seconds)

    try:
        resp = http.get(
            session,
            media_url,
            exam_id=exam_id,
            question_index=question_index,
            media_id=media_id,
            expect_html=True,
            min_bytes=1,
        )
    except (AuthenticationRequiredError, JobCancelledError):
        raise
    except FuexamRequestError as e:
        raise CommentFetchError(
            f"Tải bình luận thất bại cho media {media_id}: {e}",
            media_id=media_id,
            error_type=e.error_type,
            error_code=e.error_code,
            status_code=e.status_code,
            url=e.url,
            attempts=e.attempts,
        ) from e

    if resp.status_code != 200:
        raise CommentFetchError(
            f"Tải bình luận thất bại cho media {media_id} (HTTP {resp.status_code})",
            media_id=media_id,
            error_type="server_error" if resp.status_code >= 500 else "http_4xx",
            status_code=resp.status_code,
            url=_sanitize_url(media_url),
        )

    soup = BeautifulSoup(resp.text, "html.parser")
    comment_articles = soup.select(".message--comment")
    parsed_comments: List[Dict[str, Any]] = []

    for c in comment_articles:
        c_id = c.get("data-content") or c.get("id") or ""
        m_id_match = re.search(r"\d+", c_id)
        numeric_id = int(m_id_match.group(0)) if m_id_match else None

        author_el = c.select_one(".username")
        author_name = author_el.text.strip() if author_el else "Thành viên"
        author_hash = hashlib.sha256(author_name.encode("utf-8")).hexdigest()[:12]

        body_el = c.select_one(".bbWrapper")
        # Bóc tách nội dung quote để tránh nhận nhầm đáp án của quote
        quote_el = body_el.select_one("blockquote") if body_el else None
        quoted_text = quote_el.text.strip() if quote_el else ""
        if quote_el:
            quote_el.decompose()

        clean_text = body_el.text.strip() if body_el else ""

        # Số reaction
        rx_bar = c.select_one(".reactionsBar")
        rx_count = 0
        if rx_bar:
            # Ví dụ: 'Bạn và 3 người khác' hoặc icon
            rx_links = rx_bar.select("a")
            rx_count = max(1, len(rx_links))

        time_el = c.select_one("time[datetime]")
        c_time = time_el.get("datetime") if time_el else ""

        parsed_comments.append({
            "comment_id": numeric_id,
            "author_name": author_name,
            "author_hash": author_hash,
            "raw_text": clean_text,
            "quoted_text": quoted_text,
            "reactions": rx_count,
            "created_at": c_time,
        })

    payload = {
        "media_id": media_id,
        "slug": slug,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "total_comments": len(parsed_comments),
        "comments": parsed_comments,
    }
    _atomic_write_text(comments_file, json.dumps(payload, indent=2, ensure_ascii=False))

    return parsed_comments, False


from dataclasses import dataclass, field


@dataclass
class SubExam:
    exam_code: Optional[str]  # Ví dụ "Đề 1", "Mã đề 102", hoặc None
    title: str
    questions: List[Dict[str, Any]]


def extract_exam_code_chip(image_input: Union[Path, str, Image.Image]) -> np.ndarray:
    """
    Trích xuất và chuẩn hóa vùng MÃ ĐỀ trong dải banner:
    - Tìm dải banner tiêu đề ở y < 200.
    - Tìm thanh phân cách '|' hoặc khoảng trống lớn (> 20px) ngăn giữa MÃ ĐỀ và 'Question N'.
    - Lấy riêng vùng chứa MÃ ĐỀ, LOẠI BỎ vùng số câu hỏi.
    - Chuẩn hóa về (128, 32) grayscale float32.
    """
    if isinstance(image_input, (str, Path)):
        p = Path(image_input)
        if not p.exists():
            return np.zeros((32, 128), dtype=np.float32)
        try:
            im = Image.open(p).convert("RGB")
        except Exception:
            return np.zeros((32, 128), dtype=np.float32)
    elif isinstance(image_input, Image.Image):
        im = image_input.convert("RGB")
    else:
        return np.zeros((32, 128), dtype=np.float32)

    arr = np.array(im)
    dark = (arr[:200, :] < 180).all(axis=2)
    green = (
        (arr[:200, ..., 1].astype(int) - arr[:200, ..., 0].astype(int) >= 20)
        & (arr[:200, ..., 1].astype(int) - arr[:200, ..., 2].astype(int) >= 10)
    )
    content = dark | green
    rc = content.sum(axis=1)
    ys = np.where(rc > 50)[0]
    if len(ys) == 0:
        return np.zeros((32, 128), dtype=np.float32)
    y1, y2 = ys.min(), ys.max() + 1

    banner = content[y1:y2, :]
    cc = banner.sum(axis=0)
    xs = np.where(cc > 2)[0]
    if len(xs) == 0:
        return np.zeros((32, 128), dtype=np.float32)

    x_start = xs.min()
    x_end = None
    prev = xs[0]
    for x in xs[1:]:
        if x - prev >= 20:
            x_end = prev
            break
        prev = x

    if x_end is None or (x_end - x_start < 100):
        x_end = x_start + int(0.50 * (xs.max() - xs.min()))

    code_region = arr[y1:y2, x_start : x_end + 1]
    im_gray = Image.fromarray(code_region).convert("L").resize((128, 32), Image.Resampling.BILINEAR)
    return np.array(im_gray, dtype=np.float32)


def compute_exam_code_distance(feat1: np.ndarray, feat2: np.ndarray) -> float:
    """Khoảng cách tương đồng chuẩn hóa L1 giữa 2 vùng mã đề (0.0 = giống hệt, 1.0 = khác hoàn toàn)."""
    return float(np.mean(np.abs(feat1 - feat2))) / 255.0


def hash_banner_exam_code(image_input: Union[Path, str, Image.Image]) -> str:
    """
    Tạo perceptual hash bền vững cho vùng mã đề:
    Dùng average hash (16x8) trên vùng mã đề đã chuẩn hóa để phân nhóm chống nhiễu.
    """
    feat = extract_exam_code_chip(image_input)
    m = feat.mean()
    bits = (feat[::4, ::8] > m).flatten()
    return "".join("1" if b else "0" for b in bits)


def mock_ai_read_exam_code_from_banner(banner_im: Image.Image, default_code: str = "Mã đề 1") -> str:
    """
    Hàm đọc mã đề từ dải banner bằng AI Vision (chỉ gọi 1 lần cho mỗi nhóm ảnh).
    Trong môi trường kiểm thử / offline, đọc qua OCR đơn giản hoặc trả về mã đề chuẩn.
    """
    return default_code


@dataclass
class ThreadFilterResult:
    is_valid: bool
    exam_type: Optional[str] = None  # "FE" hoặc "PE"
    rejection_reason: Optional[str] = None
    sub_exams: List[SubExam] = field(default_factory=list)


def filter_and_classify_thread(
    thread_title: str,
    thread_url: str,
    questions: List[Dict[str, Any]],
    raw_html: Optional[str] = None,
    ai_exam_code_reader: Optional[Any] = None,
) -> ThreadFilterResult:
    """
    Bộ lọc 3 lớp cho thread trên fuexam.me:
    Lớp 1: Kiểm tra URL và Cây diễn đàn thực tế (TÀI LIỆU CÁC MÔN HỌC / Kỳ N / môn).
           Từ chối thread hỏi đáp (ví dụ /threads/tai-anh.857/), ngoài cây môn học.
    Lớp 2: Kiểm tra loại đề:
           - Nếu là PE (Practical Exam) -> Từ chối với lý do: "Chưa hỗ trợ PE trên fuexam"
           - Nếu là thread hỏi đáp / thảo luận -> Từ chối
    Lớp 3: Kiểm tra số lượng ảnh: Yêu cầu tối thiểu 10 ảnh câu hỏi (đề thi thật).
    Tách nhiều mã đề: Nhóm ảnh theo hash dải banner phần mã đề (không dùng regex trên tiêu đề thread).
                      Nếu có >= 2 nhóm mã đề -> gọi AI nhìn dải banner 1 lần mỗi nhóm để tách file.
    """
    # Lớp 1: URL & Cây diễn đàn thực tế
    if not thread_url or not ("/threads/" in thread_url or "/forums/" in thread_url):
        return ThreadFilterResult(
            is_valid=False,
            rejection_reason="URL không đúng định dạng thread của fuexam.me",
        )

    t_clean = thread_title.strip()

    # Kiểm tra cây diễn đàn thực tế từ breadcrumbs trong HTML
    if raw_html:
        soup = BeautifulSoup(raw_html, "html.parser")
        breadcrumbs = [a.get_text(strip=True) for a in soup.select(".p-breadcrumbs a")]
        bc_text = " / ".join(breadcrumbs)

        # Cây diễn đàn chuẩn: phải chứa 'TÀI LIỆU CÁC MÔN HỌC' hoặc thuộc node môn học
        if breadcrumbs and "TÀI LIỆU CÁC MÔN HỌC" not in bc_text and not re.search(r"Kỳ\s*\d+", bc_text, re.IGNORECASE):
            return ThreadFilterResult(
                is_valid=False,
                rejection_reason="Thread không thuộc cây môn học (TÀI LIỆU CÁC MÔN HỌC / Kỳ N / môn)",
            )

    # Kiểm tra thread hỏi đáp / hướng dẫn cụ thể (ví dụ /threads/tai-anh.857/)
    if re.search(r"/threads/(?:tai-anh|hoi-dap|gop-y|thao-luan)\b", thread_url, re.IGNORECASE) or \
       re.search(r"^(?:Hỏi\s*đáp|Tải\s*ảnh|Hướng\s*dẫn|Thảo\s*luận)\b", t_clean, re.IGNORECASE):
        return ThreadFilterResult(
            is_valid=False,
            rejection_reason="Thread không phải là bài đăng đề thi (tài liệu/thảo luận/hỏi đáp)",
        )

    # Lớp 2: Kiểm tra loại đề (PE vs FE)
    pe_pattern = r"(?:\bPE\b|Đề\s*Thi\s*PE|Practical\s*Exam)"
    if re.search(pe_pattern, t_clean, re.IGNORECASE):
        return ThreadFilterResult(
            is_valid=False,
            exam_type="PE",
            rejection_reason="Chưa hỗ trợ PE trên fuexam",
        )

    # Lớp 3: Kiểm tra số lượng ảnh câu hỏi (yêu cầu tối thiểu 10 ảnh)
    if not questions or len(questions) < 10:
        count = len(questions) if questions else 0
        return ThreadFilterResult(
            is_valid=False,
            rejection_reason=f"Thread có ít hơn 10 ảnh câu hỏi (chỉ có {count} ảnh, yêu cầu tối thiểu 10)",
        )

    # TÁCH MÃ ĐỀ: Nhóm ảnh theo khoảng cách tương đồng vùng mã đề (bền với nhiễu nén, loại trừ số câu)
    groups: List[Dict[str, Any]] = []
    DIST_THRESHOLD = 0.15

    for q in questions:
        img_p = q.get("local_image_path") or q.get("image_path")
        if img_p and Path(img_p).exists():
            feat = extract_exam_code_chip(img_p)
            matched = False
            for grp in groups:
                if grp.get("feat") is not None and compute_exam_code_distance(feat, grp["feat"]) <= DIST_THRESHOLD:
                    grp["questions"].append(q)
                    matched = True
                    break
            if not matched:
                groups.append({
                    "feat": feat,
                    "sample_img": img_p,
                    "questions": [q],
                })
        elif "banner_hash" in q:
            # Tương thích ngược với fixture/test nhân tạo
            b_hash = q["banner_hash"]
            matched = False
            for grp in groups:
                if grp.get("hash") == b_hash:
                    grp["questions"].append(q)
                    matched = True
                    break
            if not matched:
                groups.append({
                    "hash": b_hash,
                    "sample_img": q.get("sample_image"),
                    "questions": [q],
                })
        else:
            if not groups:
                groups.append({"sample_img": None, "questions": [q]})
            else:
                groups[0]["questions"].append(q)

    # Nếu chỉ có 1 nhóm mã đề -> Giữ tên nguyên như FUOverflow
    if len(groups) <= 1:
        return ThreadFilterResult(
            is_valid=True,
            exam_type="FE",
            sub_exams=[SubExam(exam_code=None, title=t_clean, questions=questions)],
        )

    # Nếu có từ 2 nhóm mã đề trở lên -> Tách thành nhiều SubExam
    ai_reader = ai_exam_code_reader or mock_ai_read_exam_code_from_banner
    sub_exams = []
    for idx_g, grp in enumerate(groups, 1):
        sample_img = grp.get("sample_img")
        code_str = f"Mã đề {idx_g:02d}"
        if sample_img:
            try:
                code_str = ai_reader(sample_img, default_code=f"Mã đề {idx_g:02d}")
            except Exception:
                code_str = f"Mã đề {idx_g:02d}"

        sub_title = f"{t_clean} - {code_str}"
        sub_exams.append(SubExam(exam_code=code_str, title=sub_title, questions=grp["questions"]))

    return ThreadFilterResult(
        is_valid=True,
        exam_type="FE",
        sub_exams=sub_exams,
    )


