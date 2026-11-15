import concurrent.futures
from datetime import datetime, date
import json
import os
from pathlib import Path
import random
import re
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger

logger = get_logger(__name__)
settings = get_settings()


class DailyQuotaExhaustedError(Exception):
    """Raised when daily AI call limit is reached."""
    pass


class AIRateLimiter:
    """
    Enforces concurrency = 1 and minimum interval between consecutive AI calls.
    Default: min_interval = 7.0s.
    """

    def __init__(self, min_interval_seconds: float = 7.0):
        self.min_interval_seconds = min_interval_seconds
        self._lock = threading.Lock()
        self._last_call_end = 0.0

    def wait_and_acquire(self) -> float:
        """
        Acquire lock and sleep if necessary to respect min_interval_seconds.
        Returns the duration slept in seconds.
        """
        self._lock.acquire()
        if self.min_interval_seconds <= 0:
            return 0.0
        now = time.monotonic()
        elapsed = now - self._last_call_end
        wait_time = max(0.0, self.min_interval_seconds - elapsed)
        if wait_time > 0:
            logger.info(f"[AIRateLimiter] Throttling: waiting {wait_time:.2f}s before next AI call...")
            time.sleep(wait_time)
        return wait_time

    def release(self):
        """Mark completion time and release lock."""
        self._last_call_end = time.monotonic()
        if self._lock.locked():
            self._lock.release()

    def __enter__(self):
        self.wait_and_acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


DEFAULT_MODEL_LIMITS: Dict[str, int] = {
    "gemini-2.5-flash": 20,
    "gemini-2.0-flash": 1500,
    "gemini-1.5-flash": 1500,
    "gemini-1.5-pro": 50,
    "llama-3.2-11b-vision-preview": 1000,
    "llama-3.2-90b-vision-preview": 1000,
}


class DailyQuotaTracker:
    """
    Tracks and persists AI calls made per day, both globally and per model.
    Enforces daily quota limit.
    """

    def __init__(
        self,
        quota_file: Optional[Path] = None,
        default_limit: int = 1500,
    ):
        self.quota_file = quota_file or (settings.STORAGE_DIR / "cache" / "ai_daily_quota.json")
        self.default_limit = default_limit
        self._lock = threading.Lock()
        self._ensure_file()

    def _ensure_file(self):
        self.quota_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.quota_file.exists():
            today_str = date.today().isoformat()
            data = {
                "date": today_str,
                "calls_today": 0,
                "daily_limit": self.default_limit,
                "exhausted": False,
                "exhausted_reason": None,
                "last_call_at": None,
                "models": {},
            }
            self.quota_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _read_data(self) -> Dict[str, Any]:
        try:
            if self.quota_file.exists():
                data = json.loads(self.quota_file.read_text(encoding="utf-8"))
                if "models" not in data:
                    data["models"] = {}
                return data
        except Exception as e:
            logger.warning(f"Could not read quota file: {e}")
        today_str = date.today().isoformat()
        return {
            "date": today_str,
            "calls_today": 0,
            "daily_limit": self.default_limit,
            "exhausted": False,
            "exhausted_reason": None,
            "last_call_at": None,
            "models": {},
        }

    def _write_data(self, data: Dict[str, Any]):
        try:
            self.quota_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Could not save quota file: {e}")

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            data = self._read_data()
            today_str = date.today().isoformat()
            if data.get("date") != today_str:
                # Reset for new day
                data["date"] = today_str
                data["calls_today"] = 0
                data["exhausted"] = False
                data["exhausted_reason"] = None
                data["models"] = {}
                self._write_data(data)
            return data

    def get_model_status(self, model: str) -> Dict[str, Any]:
        status = self.get_status()
        models = status.setdefault("models", {})
        if model not in models:
            limit = DEFAULT_MODEL_LIMITS.get(model, self.default_limit)
            models[model] = {
                "calls_today": 0,
                "daily_limit": limit,
                "exhausted": False,
                "exhausted_reason": None,
            }
        return models[model]

    def can_call(self, model: Optional[str] = None) -> bool:
        if model:
            m_stat = self.get_model_status(model)
            if m_stat.get("exhausted", False):
                return False
            calls = m_stat.get("calls_today", 0)
            limit = m_stat.get("daily_limit", DEFAULT_MODEL_LIMITS.get(model, self.default_limit))
            return calls < limit

        status = self.get_status()
        if status.get("exhausted", False):
            return False
        calls = status.get("calls_today", 0)
        limit = status.get("daily_limit", self.default_limit)
        return calls < limit

    def record_call(self, model: Optional[str] = None) -> int:
        with self._lock:
            data = self._read_data()
            today_str = date.today().isoformat()
            if data.get("date") != today_str:
                data["date"] = today_str
                data["calls_today"] = 0
                data["exhausted"] = False
                data["exhausted_reason"] = None
                data["models"] = {}

            data["calls_today"] = data.get("calls_today", 0) + 1
            data["last_call_at"] = datetime.utcnow().isoformat()
            limit = data.get("daily_limit", self.default_limit)
            if data["calls_today"] >= limit:
                data["exhausted"] = True
                data["exhausted_reason"] = f"Daily limit reached ({limit})"

            if model:
                models = data.setdefault("models", {})
                m_stat = models.setdefault(model, {
                    "calls_today": 0,
                    "daily_limit": DEFAULT_MODEL_LIMITS.get(model, self.default_limit),
                    "exhausted": False,
                    "exhausted_reason": None,
                })
                m_stat["calls_today"] = m_stat.get("calls_today", 0) + 1
                if m_stat["calls_today"] >= m_stat.get("daily_limit", self.default_limit):
                    m_stat["exhausted"] = True
                    m_stat["exhausted_reason"] = f"Model daily limit reached ({m_stat['daily_limit']})"

            self._write_data(data)
            return data["calls_today"]

    def mark_exhausted(self, reason: str = "Daily limit exceeded", model: Optional[str] = None):
        with self._lock:
            data = self._read_data()
            if model:
                models = data.setdefault("models", {})
                m_stat = models.setdefault(model, {
                    "calls_today": 0,
                    "daily_limit": DEFAULT_MODEL_LIMITS.get(model, self.default_limit),
                    "exhausted": False,
                    "exhausted_reason": None,
                })
                m_stat["exhausted"] = True
                m_stat["exhausted_reason"] = reason
                logger.warning(f"[DailyQuotaTracker] Model '{model}' quota marked as EXHAUSTED: {reason}")
            else:
                data["exhausted"] = True
                data["exhausted_reason"] = reason
                logger.warning(f"[DailyQuotaTracker] AI quota marked as EXHAUSTED: {reason}")
            self._write_data(data)

    def remaining_calls(self, model: Optional[str] = None) -> int:
        if model:
            m_stat = self.get_model_status(model)
            if m_stat.get("exhausted", False):
                return 0
            limit = m_stat.get("daily_limit", DEFAULT_MODEL_LIMITS.get(model, self.default_limit))
            return max(0, limit - m_stat.get("calls_today", 0))

        status = self.get_status()
        if status.get("exhausted", False):
            return 0
        limit = status.get("daily_limit", self.default_limit)
        return max(0, limit - status.get("calls_today", 0))


class CheckpointManager:
    """
    Saves and loads progress checkpoints to resume evaluation/jobs seamlessly.
    Keeps memory copy for fast batch processing.
    """

    def __init__(self, checkpoint_file: Optional[Path] = None):
        self.checkpoint_file = checkpoint_file or (settings.STORAGE_DIR / "cache" / "ai_audit_checkpoint.json")
        self.checkpoint_file.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._data: Optional[Dict[str, Any]] = None

    def load(self) -> Dict[str, Any]:
        with self._lock:
            if self._data is not None:
                return self._data
            if self.checkpoint_file.exists():
                try:
                    self._data = json.loads(self.checkpoint_file.read_text(encoding="utf-8"))
                    return self._data
                except Exception as e:
                    logger.warning(f"Failed to read checkpoint file: {e}")
            self._data = {
                "started_at": datetime.utcnow().isoformat(),
                "completed_question_ids": [],
                "results": {},
            }
            return self._data

    def save(self, data: Optional[Dict[str, Any]] = None):
        with self._lock:
            if data is not None:
                self._data = data
            if self._data is None:
                self.load()
            try:
                self._data["last_updated_at"] = datetime.utcnow().isoformat()
                self.checkpoint_file.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
            except Exception as e:
                logger.warning(f"Failed to save checkpoint file: {e}")

    def is_processed(self, question_id: int) -> bool:
        data = self.load()
        return question_id in data.get("completed_question_ids", [])

    def mark_processed(self, question_id: int, result_summary: Optional[Dict[str, Any]] = None):
        with self._lock:
            data = self.load()
            c_ids = set(data.get("completed_question_ids", []))
            c_ids.add(question_id)
            data["completed_question_ids"] = list(c_ids)
            if result_summary:
                results = data.get("results", {})
                results[str(question_id)] = result_summary
                data["results"] = results
            self._data = data
            self.save()


# Global singletons
_default_ai_rate_limiter: Optional[AIRateLimiter] = None
_provider_rate_limiters: Dict[str, AIRateLimiter] = {}
_rate_limiter_lock = threading.Lock()
_default_daily_quota_tracker: Optional[DailyQuotaTracker] = None


def get_ai_rate_limiter(min_interval: float = 7.0, provider_name: Optional[str] = None) -> AIRateLimiter:
    """
    Returns an AIRateLimiter. If provider_name is specified, returns a rate limiter
    dedicated to that specific provider, ensuring the 7s throttle only applies
    between consecutive calls to the SAME provider and does NOT delay switching
    to another provider.
    """
    global _default_ai_rate_limiter, _provider_rate_limiters
    with _rate_limiter_lock:
        if provider_name:
            norm_name = provider_name.strip().lower()
            if norm_name not in _provider_rate_limiters:
                _provider_rate_limiters[norm_name] = AIRateLimiter(min_interval_seconds=min_interval)
            return _provider_rate_limiters[norm_name]

        if _default_ai_rate_limiter is None:
            _default_ai_rate_limiter = AIRateLimiter(min_interval_seconds=min_interval)
        return _default_ai_rate_limiter


def get_daily_quota_tracker(default_limit: int = 1500) -> DailyQuotaTracker:
    global _default_daily_quota_tracker
    if _default_daily_quota_tracker is None:
        _default_daily_quota_tracker = DailyQuotaTracker(default_limit=default_limit)
    return _default_daily_quota_tracker


def parse_retry_after(error: Exception) -> Optional[float]:
    """
    Inspect exception and error message/headers for Retry-After duration in seconds.
    """
    err_str = str(error)

    # Check response headers if present on error
    response = getattr(error, "response", None)
    if response is not None:
        headers = getattr(response, "headers", {})
        if headers:
            retry_header = headers.get("retry-after") or headers.get("Retry-After")
            if retry_header:
                try:
                    return float(retry_header)
                except ValueError:
                    pass

    # Regex matches in error message:
    # e.g. "retry after 12s", "retry-after: 15", "retry in 8.5 seconds", "try again in 20s"
    patterns = [
        r"retry[ -]after[:\s]+(\d+(?:\.\d+)?)",
        r"retry in (\d+(?:\.\d+)?)\s*s",
        r"try again in (\d+(?:\.\d+)?)\s*s",
        r"quota exceeded.*?(\d+(?:\.\d+)?)\s*s",
        r"wait (\d+(?:\.\d+)?)\s*s",
    ]
    for pat in patterns:
        m = re.search(pat, err_str, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass

    return None


def execute_with_timeout(fn: Callable[..., Any], timeout_seconds: float = 60.0, *args, **kwargs) -> Any:
    """
    Execute callable fn with a hard timeout in seconds using a single worker thread.
    Raises TimeoutError if execution exceeds timeout_seconds.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(fn, *args, **kwargs)
        try:
            return future.result(timeout=timeout_seconds)
        except concurrent.futures.TimeoutError:
            raise TimeoutError(f"Call timed out after {timeout_seconds}s")
