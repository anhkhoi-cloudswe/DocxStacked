import os
import shutil
import tempfile
from datetime import date
from pathlib import Path
import pytest
from backend.app.core.config import get_settings
from backend.app.db.session import init_db, rebind_db_engines
from backend.app.modules.analysis.gemini_guard import get_daily_quota_tracker

@pytest.fixture(autouse=True, scope="session")
def anyio_backend():
    return "asyncio"

@pytest.fixture(autouse=True, scope="session")
def isolate_test_data_dir():
    """Ensure all pytest suites write strictly to a temporary DOCXSTACKED_DATA_DIR, cleaned up after."""
    temp_dir = tempfile.mkdtemp(prefix="docxstacked_pytest_")
    old_env = os.environ.get("DOCXSTACKED_DATA_DIR")
    os.environ["DOCXSTACKED_DATA_DIR"] = temp_dir
    get_settings.cache_clear()
    rebind_db_engines()
    
    yield temp_dir
    
    # Cleanup session
    import backend.app.db.session as s_mod
    import asyncio
    try:
        asyncio.run(s_mod.async_engine.dispose())
    except Exception:
        pass
    try:
        s_mod.sync_engine.dispose()
    except Exception:
        pass

    if old_env is not None:
        os.environ["DOCXSTACKED_DATA_DIR"] = old_env
    else:
        os.environ.pop("DOCXSTACKED_DATA_DIR", None)
    get_settings.cache_clear()
    rebind_db_engines()

    try:
        shutil.rmtree(temp_dir, ignore_errors=True)
    except Exception:
        pass

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

