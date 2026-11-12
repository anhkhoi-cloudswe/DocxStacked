import pytest
from backend.app.db.session import init_db

@pytest.fixture(autouse=True, scope="session")
def anyio_backend():
    return "asyncio"

@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()

