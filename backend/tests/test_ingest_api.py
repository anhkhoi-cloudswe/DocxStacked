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
