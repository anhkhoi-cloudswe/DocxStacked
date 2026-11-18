import pytest
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.core.config import get_settings

settings = get_settings()
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
    payload = {
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

    payload1 = {
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

