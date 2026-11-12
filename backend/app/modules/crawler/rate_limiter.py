import asyncio
import random
import threading
import time
from typing import Optional

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger

logger = get_logger(__name__)


class RateLimiter:
    """
    Rate Limiter with:
    1. Random delay between requests (default 1.5 - 4.0 seconds, configurable).
    2. Strict serialization (concurrency = 1) using asyncio.Lock & threading.Lock.
    Protects against bot detection, WAF 403 blocks, and server overload.
    """

    def __init__(
        self,
        min_delay: Optional[float] = None,
        max_delay: Optional[float] = None,
        concurrency: int = 1,
    ):
        settings = get_settings()
        crawl_cfg = settings.yaml_config.crawl
        delays = crawl_cfg.delay_seconds if len(crawl_cfg.delay_seconds) == 2 else [1.5, 4.0]

        self.min_delay = min_delay if min_delay is not None else delays[0]
        self.max_delay = max_delay if max_delay is not None else delays[1]
        self.concurrency = concurrency or crawl_cfg.concurrency

        self._async_lock = asyncio.Lock()
        self._sync_lock = threading.Lock()
        self._last_request_time = 0.0

    def _get_random_delay(self) -> float:
        return random.uniform(self.min_delay, self.max_delay)

    async def async_wait(self) -> float:
        """Wait asynchronously to enforce minimum delay between consecutive calls."""
        async with self._async_lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            delay = self._get_random_delay()
            wait_time = max(0.0, delay - elapsed)
            if wait_time > 0:
                logger.debug(f"[RateLimiter] Async throttle waiting {wait_time:.2f}s...")
                await asyncio.sleep(wait_time)
            self._last_request_time = time.monotonic()
            return wait_time

    wait_async = async_wait

    def sync_wait(self) -> float:
        """Wait synchronously to enforce minimum delay between consecutive calls."""
        with self._sync_lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            delay = self._get_random_delay()
            wait_time = max(0.0, delay - elapsed)
            if wait_time > 0:
                logger.debug(f"[RateLimiter] Sync throttle waiting {wait_time:.2f}s...")
                time.sleep(wait_time)
            self._last_request_time = time.monotonic()
            return wait_time

    wait_sync = sync_wait


# Global default instance
_default_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    global _default_rate_limiter
    if _default_rate_limiter is None:
        _default_rate_limiter = RateLimiter()
    return _default_rate_limiter

