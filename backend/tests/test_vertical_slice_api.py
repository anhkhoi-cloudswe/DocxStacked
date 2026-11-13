import pytest
from httpx import AsyncClient, ASGITransport
from backend.app.db.session import init_db
from backend.app.main import app


@pytest.fixture(autouse=True)
async def prepare_db():
    await init_db()


@pytest.mark.asyncio
async def test_api_subjects_list():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/subjects?q=CSD202")
        assert resp.status_code == 200
        data = resp.json()
        items = data["items"] if isinstance(data, dict) and "items" in data else data
        assert isinstance(items, list)
        assert len(items) >= 1
        assert any(s["code"] == "CSD202" for s in items)


@pytest.mark.asyncio
async def test_api_job_create_and_status():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Create job
        resp = await client.post("/api/jobs", json={
            "subject_code": "CSD202",
            "exam_type": "FE",
            "limit": 1
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        job_id = data["job_id"]
        assert data["subject_code"] == "CSD202"

        # Check job status
        status_resp = await client.get(f"/api/jobs/{job_id}")
        assert status_resp.status_code == 200
        status_data = status_resp.json()
        assert status_data["job_id"] == job_id
        assert status_data["status"] in ("pending", "running", "completed")


@pytest.mark.asyncio
async def test_api_job_create_with_specific_exam_ids():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/jobs", json={
            "subject_code": "PRM392",
            "exam_type": "FE",
            "limit": 1,
            "exam_ids": [42]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert data["subject_code"] == "PRM392"
        assert data["exam_count"] == 1
        assert data["details"]["exam_ids"] == [42]
