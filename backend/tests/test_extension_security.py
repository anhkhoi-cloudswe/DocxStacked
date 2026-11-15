"""
Tests for Task 1: Extension ID pinning, Host header validation, and Origin security checks.
"""
from pathlib import Path
from fastapi.testclient import TestClient
import pytest

from backend.app.main import app
from backend.app.core.config import get_settings

settings = get_settings()
client = TestClient(app)


def test_invalid_host_header_rejected_with_403():
    """
    DNS Rebinding protection:
    If Host is not 127.0.0.1, localhost, or testserver, return 403.
    """
    res = client.post(
        "/api/ingest",
        json={
            "subject_code": "MLN122",
            "exam_title": "MLN122 - SU26 - RE",
            "questions": [],
        },
        headers={
            "Host": "attacker.evil.com:8000",
            "Origin": f"chrome-extension://{settings.EXTENSION_ID}",
        },
    )
    assert res.status_code == 403
    assert "Host 'attacker.evil.com' không hợp lệ" in res.json()["detail"]


def test_arbitrary_website_origin_rejected_with_403():
    """
    Arbitrary external websites (e.g. evil-tracker.com) must be rejected with 403 Forbidden.
    """
    res = client.post(
        "/api/ingest",
        json={
            "subject_code": "MLN122",
            "exam_title": "MLN122 - SU26 - RE",
            "questions": [],
        },
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": "https://evil-tracker.com",
        },
    )
    assert res.status_code == 403
    assert "không được cấp quyền" in res.json()["detail"]


def test_valid_pinned_extension_id_accepted_without_token(tmp_path, monkeypatch):
    """
    When Origin matches the pinned extension ID (chrome-extension://<EXTENSION_ID>),
    requests are accepted directly without requiring manual token entry.
    """
    # Prevent tests from writing to data/output production directory
    monkeypatch.setattr(settings, "STORAGE_DIR", tmp_path)
    res = client.post(
        "/api/ingest",
        json={
            "subject_code": "TEST101",
            "exam_title": "TEST101 - SU26 - FE",
            "questions": [],
            "options": {"ai_enabled": False},
        },
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": f"chrome-extension://{settings.EXTENSION_ID}",
        },
    )
    assert res.status_code == 200
    assert res.json()["status"] == "success"


def test_other_unauthorized_extension_id_rejected_with_403():
    """
    An extension with a different extension ID must be rejected with 403 Forbidden.
    """
    res = client.post(
        "/api/ingest",
        json={
            "subject_code": "MLN122",
            "exam_title": "MLN122 - SU26 - RE",
            "questions": [],
        },
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": "chrome-extension://zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz",
        },
    )
    assert res.status_code == 403
    assert "không được cấp quyền" in res.json()["detail"]


def test_ping_without_token_pinned_origin_returns_200():
    """
    GET /api/ingest/ping must return 200 without token when Origin matches pinned extension.
    """
    res = client.get(
        "/api/ingest/ping",
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": f"chrome-extension://{settings.EXTENSION_ID}",
        },
    )
    assert res.status_code == 200
    assert res.json().get("status") == "ok"


def test_ping_arbitrary_website_origin_rejected_with_403():
    """
    GET /api/ingest/ping must reject unknown website Origin with 403.
    """
    res = client.get(
        "/api/ingest/ping",
        headers={
            "Host": "127.0.0.1:8000",
            "Origin": "https://unknown-evil-site.com",
        },
    )
    assert res.status_code == 403
    assert "không được cấp quyền" in res.json()["detail"]


def test_ping_invalid_host_header_rejected_with_403():
    """
    GET /api/ingest/ping must reject invalid Host with 403.
    """
    res = client.get(
        "/api/ingest/ping",
        headers={
            "Host": "attacker.evil.com:8000",
            "Origin": f"chrome-extension://{settings.EXTENSION_ID}",
        },
    )
    assert res.status_code == 403
    assert "Host 'attacker.evil.com' không hợp lệ" in res.json()["detail"]


def test_sidepanel_no_mandatory_token_prompt_grep():
    """
    Verify sidepanel.js does not contain the mandatory token blocking string.
    """
    sidepanel_js = Path("extension/sidepanel.js")
    assert sidepanel_js.exists()
    content = sidepanel_js.read_text(encoding="utf-8")
    assert "Ingest Token ... trước khi bắt đầu" not in content
    assert "Vui lòng dán Ingest Token từ trang Cài đặt DocxStacked vào ô Token trước khi bắt đầu!" not in content
    assert "alert(" not in content
    assert "confirm(" not in content

