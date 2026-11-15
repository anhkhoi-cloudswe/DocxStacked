from datetime import date
import pytest
from backend.app.db.session import init_db
from backend.app.modules.analysis.gemini_guard import get_daily_quota_tracker

@pytest.fixture(autouse=True, scope="session")
def anyio_backend():
    return "asyncio"

@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()

@pytest.fixture(autouse=True)
def reset_daily_quota():
    tracker = get_daily_quota_tracker()
    with tracker._lock:
        today_str = date.today().isoformat()
        reset_data = {
            "date": today_str,
            "calls_today": 0,
            "daily_limit": 1500,
            "exhausted": False,
            "exhausted_reason": None,
            "last_call_at": None,
        }
        tracker._write_data(reset_data)

