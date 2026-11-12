import pytest
from httpx import AsyncClient, ASGITransport
from backend.app.main import app
from backend.app.core.config import get_settings

settings = get_settings()


@pytest.mark.asyncio
async def test_auth_status_not_logged_in():
    cookies_file = settings.DATA_DIR / "auth" / "cookies.json"
    backup = None
    if cookies_file.exists():
        backup = cookies_file.read_bytes()
        cookies_file.unlink()

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/auth/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["logged_in"] is False
            assert data["status_code"] in ("not_logged_in", "profile_locked")
            assert "Chưa đăng nhập" in data["detail"] or "khoá" in data["detail"]
    finally:
        if backup is not None:
            cookies_file.parent.mkdir(parents=True, exist_ok=True)
            cookies_file.write_bytes(backup)


@pytest.mark.asyncio
async def test_auth_login_session_endpoints():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Get session state
        resp = await client.get("/api/auth/login-session")
        assert resp.status_code == 200
        data = resp.json()
        assert "state" in data
        assert isinstance(data.get("recent_logs"), list)

        # 2. Cancel session
        resp_cancel = await client.post("/api/auth/login-session/cancel")
        assert resp_cancel.status_code == 200
        assert resp_cancel.json()["success"] is True

        # 3. Unlock profile
        resp_unlock = await client.post("/api/auth/login-session/unlock")
        assert resp_unlock.status_code == 200
        assert resp_unlock.json()["success"] is True


@pytest.mark.asyncio
async def test_auth_cookies_validation():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Invalid empty string
        resp = await client.post("/api/auth/cookies", json={"cookie_string": ""})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "trống" in data["message"].lower()

        # Invalid format
        resp = await client.post("/api/auth/cookies", json={"cookie_string": "invalid_random_string"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "không tìm thấy" in data["message"].lower()
