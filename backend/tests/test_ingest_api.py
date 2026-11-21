import pytest
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.core.config import get_settings

class SettingsProxy:
    def __getattr__(self, name: str):
        return getattr(get_settings(), name)

settings = SettingsProxy()
client = TestClient(app)

def test_ingest_security_rejection():
    """Verify that requests without token or with invalid origin are rejected."""
    # 1. Missing Token & Missing Header -> 403 (or 401)
    res = client.post(
        "/api/ingest",
        json={"subject_code": "TEST", "exam_title": "Test", "questions": []},
    )
    assert res.status_code in (401, 403)

    # 2. Invalid Token & Missing Header -> 403 (or 401)
    res_bad = client.post(
        "/api/ingest",
        json={"subject_code": "TEST", "exam_title": "Test", "questions": []},
        headers={"X-Ingest-Token": "bad_token"}
    )
    assert res_bad.status_code in (401, 403)

    # 3. Disallowed external origin -> 403
    res_origin = client.post(
        "/api/ingest",
        json={"subject_code": "TEST", "exam_title": "Test", "questions": []},
        headers={
            "X-Ingest-Token": settings.INGEST_TOKEN,
            "Origin": "https://attacker.site",
        }
    )
    assert res_origin.status_code == 403

def test_ingest_security_acceptance():
    """Verify that requests with valid INGEST_TOKEN and valid origin are accepted."""
    from backend.app.api.ingest import _verify_ingest_access
    
    class FakeLocalRequest:
        method = "POST"
        url = type("URL", (), {"path": "/api/ingest"})()
        headers = {"origin": "http://127.0.0.1:8000"}
        client = None
        
    # Should not raise exception with valid token
    _verify_ingest_access(FakeLocalRequest(), token=settings.INGEST_TOKEN)

    class FakeExtensionRequest:
        method = "POST"
        url = type("URL", (), {"path": "/api/ingest"})()
        headers = {"origin": f"chrome-extension://{settings.EXTENSION_ID}"}
        client = None
        
    _verify_ingest_access(FakeExtensionRequest(), token=settings.INGEST_TOKEN)

def test_ingest_payload_flow():
    """Test standard ingest flow creating an exam with minimal dummy question."""
    # Ensure active runs are cleared before test
    client.post("/api/ingest/clear-runs", headers={"X-Ingest-Token": settings.INGEST_TOKEN})

    payload = {
        "run_id": "test_run_flow_01",
        "subject_code": "TEST101",
        "exam_title": "TEST101 - Ingest Unit Test",
        "exam_url": "https://fuoverflow.com/threads/test101-unit.9999/",
        "term": "SU26",
        "exam_type": "FE",
        "questions": [
            {
                "index": 1,
                "file_name": "q001.png",
                "media_id": "test_m1",
                "media_url": "https://fuoverflow.com/media/1/",
                "image_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
                "comments": [
                    {
                        "comment_id": "c1",
                        "author_hash": "user1",
                        "raw_text": "A",
                        "upvotes": 5,
                        "is_reply": False
                    }
                ]
            }
        ],
        "options": {
            "ai_enabled": False
        }
    }
    
    response = client.post(
        "/api/ingest",
        json=payload,
        headers={"X-Ingest-Token": settings.INGEST_TOKEN}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["questions_ingested"] == 1
    assert data["comments_ingested"] == 1
    assert "docx_path" in data

    # Test check-exam timezone ISO format
    check_resp = client.get(
        f"/api/ingest/check-exam?url={payload['exam_url']}",
        headers={"X-Ingest-Token": settings.INGEST_TOKEN}
    )
    assert check_resp.status_code == 200
    check_data = check_resp.json()
    assert check_data["exists"] is True
    assert check_data["compiled_at_iso"] is not None
    assert check_data["compiled_at_iso"].endswith("Z")
    assert "T" in check_data["compiled_at_iso"]


def test_ingest_duplicate_thread_deduplication():
    """Verify that ingesting the same thread twice (even with /unread or notification prefix) results in exactly ONE exam."""
    import sqlite3
    client.post("/api/ingest/clear-runs", headers={"X-Ingest-Token": settings.INGEST_TOKEN})

    payload1 = {
        "run_id": "test_run_dedup_01",
        "subject_code": "TEST102",
        "exam_title": "(2) Đề Thi FE - TEST102 - Thread Dedup Test",
        "exam_url": "https://fuoverflow.com/threads/test-thread-dedup.7777/",
        "term": "SU26",
        "exam_type": "FE",
        "questions": [
            {
                "index": 1,
                "file_name": "q001.png",
                "image_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
                "comments": [{"raw_text": "B", "upvotes": 2}]
            }
        ],
        "options": {"ai_enabled": False}
    }

    # First ingest
    res1 = client.post("/api/ingest", json=payload1, headers={"X-Ingest-Token": settings.INGEST_TOKEN})
    assert res1.status_code == 200
    data1 = res1.json()
    exam_id_1 = data1["exam_id"]
    assert data1["exam_title"] == "TEST102 - Thread Dedup Test"

    # Second ingest with /unread and different raw title
    payload2 = {
        "run_id": "test_run_dedup_01",
        "subject_code": "TEST102",
        "exam_title": "[Đề Thi FE] TEST102 - Thread Dedup Test",
        "exam_url": "https://fuoverflow.com/threads/test-thread-dedup.7777/unread",
        "term": "SU26",
        "exam_type": "FE",
        "questions": [
            {
                "index": 1,
                "file_name": "q001.png",
                "image_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
                "comments": [{"raw_text": "B", "upvotes": 3}]
            }
        ],
        "options": {"ai_enabled": False}
    }

    res2 = client.post("/api/ingest", json=payload2, headers={"X-Ingest-Token": settings.INGEST_TOKEN})
    assert res2.status_code == 200
    data2 = res2.json()
    exam_id_2 = data2["exam_id"]

    # Must be the exact same exam ID
    assert exam_id_1 == exam_id_2

    # Query DB directly to guarantee only 1 exam exists for thread 7777
    from backend.app.db.session import sync_engine
    with sync_engine.connect() as conn:
        from sqlalchemy import text
        rows = conn.execute(text("SELECT id, title, url FROM exams WHERE url LIKE '%7777%'")).fetchall()

    assert len(rows) == 1, f"Expected 1 exam for thread 7777, got {len(rows)}: {rows}"
    assert rows[0][1] == "TEST102 - Thread Dedup Test"
    assert rows[0][2] == "https://fuoverflow.com/threads/test-thread-dedup.7777/"


def test_ingest_run_id_and_url_validation():
    """Verify Requirement 3: Payload must carry valid runId and exam_url, matching active run."""
    client.post("/api/ingest/clear-runs", headers={"X-Ingest-Token": settings.INGEST_TOKEN})

    base_payload = {
        "subject_code": "PRM392",
        "exam_title": "PRM392 - SU 2024 - RE",
        "questions": [
            {
                "index": 1,
                "file_name": "q001.png",
                "image_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
                "comments": []
            }
        ],
    }

    # 1. Missing runId -> 422
    p_no_run = dict(base_payload)
    p_no_run["exam_url"] = "https://fuoverflow.com/threads/prm392-su24.5000/"
    res = client.post("/api/ingest", json=p_no_run, headers={"X-Ingest-Token": settings.INGEST_TOKEN})
    assert res.status_code == 422
    assert "runId" in res.json()["detail"]

    # 2. Missing exam_url -> 422
    p_no_url = dict(base_payload)
    p_no_url["run_id"] = "run_test_123"
    res = client.post("/api/ingest", json=p_no_url, headers={"X-Ingest-Token": settings.INGEST_TOKEN})
    assert res.status_code == 422
    assert "url" in res.json()["detail"]

    # 3. Register an active run for PRM392
    reg_res = client.post(
        "/api/ingest/register-run",
        json={
            "runId": "run_prm392_valid",
            "subjectCode": "PRM392",
            "examUrls": ["https://fuoverflow.com/threads/prm392-su24.5000/"]
        },
        headers={"X-Ingest-Token": settings.INGEST_TOKEN}
    )
    assert reg_res.status_code == 200

    # 4. Old crawler sends payload with outdated runId (e.g. from PRN212) -> 409 Conflict
    p_stale_run = dict(base_payload)
    p_stale_run["run_id"] = "run_prn212_old"
    p_stale_run["exam_url"] = "https://fuoverflow.com/threads/prn212-b5.4930/"
    res = client.post("/api/ingest", json=p_stale_run, headers={"X-Ingest-Token": settings.INGEST_TOKEN})
    assert res.status_code == 409
    assert "runId" in res.json()["detail"]

    # 5. Crawler sends active runId but mismatched URL (not in active run's exam list) -> 409 Conflict
    p_mismatched_url = dict(base_payload)
    p_mismatched_url["run_id"] = "run_prm392_valid"
    p_mismatched_url["exam_url"] = "https://fuoverflow.com/threads/prn212-b5.4930/"
    res = client.post("/api/ingest", json=p_mismatched_url, headers={"X-Ingest-Token": settings.INGEST_TOKEN})
    assert res.status_code == 409
    assert "không khớp" in res.json()["detail"]

    # 6. Valid runId and matching URL -> 200 OK
    p_valid = dict(base_payload)
    p_valid["run_id"] = "run_prm392_valid"
    p_valid["exam_url"] = "https://fuoverflow.com/threads/prm392-su24.5000/"
    res = client.post("/api/ingest", json=p_valid, headers={"X-Ingest-Token": settings.INGEST_TOKEN})
    assert res.status_code == 200


def test_ingest_run_cancel_and_expiration():
    """Requirement 4: Verify active run cancellation, replacement and expiration TTL."""
    from datetime import datetime, timezone, timedelta
    import backend.app.api.ingest as ingest_mod

    # 1. Clear runs
    client.post("/api/ingest/clear-runs", headers={"X-Ingest-Token": settings.INGEST_TOKEN})

    # 2. Register run 1
    reg1 = client.post(
        "/api/ingest/register-run",
        json={"runId": "run_001", "subjectCode": "PRM392", "examUrls": ["https://fuoverflow.com/threads/prm392.1/"]},
        headers={"X-Ingest-Token": settings.INGEST_TOKEN}
    )
    assert reg1.status_code == 200
    active = client.get("/api/ingest/active-run", headers={"X-Ingest-Token": settings.INGEST_TOKEN}).json()
    assert active["active_run"]["run_id"] == "run_001"

    # 3. Register run 2 -> replaces run 1
    reg2 = client.post(
        "/api/ingest/register-run",
        json={"runId": "run_002", "subjectCode": "PRM393", "examUrls": ["https://fuoverflow.com/threads/prm393.2/"]},
        headers={"X-Ingest-Token": settings.INGEST_TOKEN}
    )
    assert reg2.status_code == 200
    active2 = client.get("/api/ingest/active-run", headers={"X-Ingest-Token": settings.INGEST_TOKEN}).json()
    assert active2["active_run"]["run_id"] == "run_002"

    # 4. Cancel run 2 via /api/ingest/cancel-run
    cancel_res = client.post(
        "/api/ingest/cancel-run",
        json={"runId": "run_002"},
        headers={"X-Ingest-Token": settings.INGEST_TOKEN}
    )
    assert cancel_res.status_code == 200
    assert cancel_res.json()["cancelled_run_id"] == "run_002"
    active_post_cancel = client.get("/api/ingest/active-run", headers={"X-Ingest-Token": settings.INGEST_TOKEN}).json()
    assert active_post_cancel["active_run"] is None

    # 5. Expiration TTL test: register run 3, age it by 301 seconds
    client.post(
        "/api/ingest/register-run",
        json={"runId": "run_003", "subjectCode": "PRN212", "examUrls": ["https://fuoverflow.com/threads/prn212.3/"]},
        headers={"X-Ingest-Token": settings.INGEST_TOKEN}
    )
    assert "run_003" in ingest_mod._active_runs
    # Artificially age the activity timestamp
    expired_time = (datetime.now(timezone.utc) - timedelta(seconds=350)).isoformat()
    ingest_mod._active_runs["run_003"]["last_activity_at"] = expired_time

    # active-run should prune and return None
    active_expired = client.get("/api/ingest/active-run", headers={"X-Ingest-Token": settings.INGEST_TOKEN}).json()
    assert active_expired["active_run"] is None
    assert "run_003" not in ingest_mod._active_runs


