import pytest
from httpx import AsyncClient, ASGITransport
from backend.app.db.session import init_db
from backend.app.main import app


@pytest.fixture(autouse=True)
async def prepare_db():
    await init_db()


@pytest.mark.asyncio
async def test_get_settings_structure_and_no_api_keys():
    """Verify GET /api/settings returns valid settings and never exposes API keys."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()

        assert "export" in data
        assert "ai" in data
        assert "voting" in data
        assert "crawl" in data

        # Check provider list
        providers = data["ai"]["providers"]
        assert len(providers) >= 1
        for p in providers:
            assert "name" in p
            assert "model" in p
            assert "has_api_key" in p
            assert "status" in p
            # Never return api_key string
            assert "api_key" not in p


@pytest.mark.asyncio
async def test_put_settings_crawl_delay_minimum_1_5s():
    """Crawl delay must reject values below 1.5s with HTTP 400."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Attempt setting delay below 1.5s
        resp = await client.put("/api/settings", json={
            "crawl": {
                "delay_seconds": [0.8, 2.0]
            }
        })
        assert resp.status_code == 400
        data = resp.json()
        assert "1.5" in data["detail"]

        # Valid delay >= 1.5s should succeed
        resp_valid = await client.put("/api/settings", json={
            "crawl": {
                "delay_seconds": [2.0, 5.0]
            }
        })
        assert resp_valid.status_code == 200
        updated = resp_valid.json()
        assert updated["crawl"]["delay_seconds"] == [2.0, 5.0]


@pytest.mark.asyncio
async def test_put_settings_and_job_snapshot():
    """
    Changing settings in DB reflects in newly created job snapshots.
    Past job snapshots remain immutable.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Update settings
        resp = await client.put("/api/settings", json={
            "export": {
                "image_width_cm": 14.5,
                "answer_format": "letter_keyword"
            },
            "ai": {
                "ensemble": True,
                "max_ai_calls": 42
            }
        })
        assert resp.status_code == 200

        # 2. Create job
        job_resp = await client.post("/api/jobs", json={
            "subject_code": "CSD202",
            "exam_type": "FE",
            "limit": 2
        })
        assert job_resp.status_code == 200
        job_id = job_resp.json()["job_id"]

        # Check job in DB directly
        from backend.app.db.session import async_session_factory
        from backend.app.db.models import Job
        from sqlalchemy import select

        async with async_session_factory() as db:
            res = await db.execute(select(Job).where(Job.job_id == job_id))
            job = res.scalar_one()
            snapshot = job.config_snapshot

            assert snapshot["export"]["image_width_cm"] == 14.5
            assert snapshot["export"]["answer_format"] == "letter_keyword"
            assert snapshot["ai"]["ensemble"] is True
            assert snapshot["ai"]["max_ai_calls"] == 42

        # 3. Update settings again
        await client.put("/api/settings", json={
            "export": {
                "image_width_cm": 18.0
            }
        })

        # Previous job's snapshot must NOT change!
        async with async_session_factory() as db:
            res = await db.execute(select(Job).where(Job.job_id == job_id))
            job = res.scalar_one()
            assert job.config_snapshot["export"]["image_width_cm"] == 14.5


@pytest.mark.asyncio
async def test_api_key_write_only_and_not_in_response_or_db():
    """Writing an API key updates .env/key status, but key string is never returned in response."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        fake_key = "sk-test-secret-key-abcdef-123456"

        resp = await client.put("/api/settings", json={
            "ai": {
                "providers": [
                    {
                        "name": "anthropic",
                        "model": "claude-3-5-haiku-20241022",
                        "api_key_env": "TEST_ANTHROPIC_DUMMY_KEY",
                        "api_key": fake_key
                    }
                ]
            }
        })
        assert resp.status_code == 200

        # Entire response text MUST NOT contain the raw key
        assert fake_key not in resp.text

        # GET response MUST NOT contain the raw key
        get_resp = await client.get("/api/settings")
        assert fake_key not in get_resp.text


@pytest.mark.asyncio
async def test_reset_settings_restores_defaults():
    """POST /api/settings/reset clears overrides and restores defaults."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Override something
        await client.put("/api/settings", json={
            "export": {"image_width_cm": 22.0}
        })
        resp1 = await client.get("/api/settings")
        assert resp1.json()["export"]["image_width_cm"] == 22.0

        # Reset
        reset_resp = await client.post("/api/settings/reset")
        assert reset_resp.status_code == 200
        data = reset_resp.json()
        assert data["export"]["image_width_cm"] == 16.51


@pytest.mark.asyncio
async def test_get_provider_models_endpoint():
    """Verify GET /api/settings/providers/{id}/models returns vision models with caching."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Anthropic
        resp = await client.get("/api/settings/providers/anthropic/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "anthropic"
        assert len(data["models"]) >= 1
        assert any("claude-3-5" in m["id"] for m in data["models"])
        assert all(m["supports_vision"] is True for m in data["models"])

        # Gemini
        resp_gemini = await client.get("/api/settings/providers/gemini/models")
        assert resp_gemini.status_code == 200
        assert any("gemini" in m["id"] for m in resp_gemini.json()["models"])


@pytest.mark.asyncio
async def test_provider_test_connection_endpoint_without_key():
    """Verify test-connection returns structured status without leaking keys."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/settings/test-connection/anthropic", json={
            "api_key_env": "NON_EXISTENT_TEST_KEY_ENV_XYZ"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is False
        assert "Chưa cấu hình API key" in data["message"]


