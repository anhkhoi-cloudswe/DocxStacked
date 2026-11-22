"""
backend/tests/test_fuexam_extension_auth.py
Kiểm thử tự động cho cơ chế đồng bộ phiên fuexam.me qua Chrome/Edge Extension:
1. Token sai -> HTTP 403 Forbidden
2. Thiếu cookie xf_user (chỉ có xf_session) -> HTTP 400 Bad Request
3. Cookie xf_user có giá trị rỗng -> HTTP 400 Bad Request
4. Probe trang fuexam.me thất bại (không có data-logged-in="true") -> HTTP 400, không lưu file
5. Probe thành công -> HTTP 200, lưu fuexam_storage_state.json + fuexam_user.json (auth_source="extension", username thật)
6. Tuyệt đối không log giá trị cookie nhạy cảm
7. Đăng xuất ở chế độ extension: KHÔNG gọi server-side POST /logout/ (để tránh logout trình duyệt thật của user), chỉ xoá file cục bộ
"""

import json
import logging
from unittest.mock import patch, MagicMock
import pytest
from httpx import AsyncClient, ASGITransport

from backend.app.main import app
from backend.app.core.config import get_settings
from backend.app.api.auth import _perform_fuexam_logout_sync, _check_fuexam_auth_file


@pytest.fixture(autouse=True)
def cleanup_auth_files():
    """Tự động dọn dẹp các file auth trước và sau mỗi test."""
    settings = get_settings()
    auth_file = settings.DATA_DIR / "auth" / "fuexam_storage_state.json"
    user_file = settings.DATA_DIR / "auth" / "fuexam_user.json"
    auth_file.unlink(missing_ok=True)
    user_file.unlink(missing_ok=True)
    yield
    auth_file.unlink(missing_ok=True)
    user_file.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_01_extension_session_wrong_token_rejected():
    """1. Xác thực Token Ingest: Token sai phải bị từ chối 403."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/auth/fuexam/extension-session",
            json={"cookies": [{"name": "xf_user", "value": "123,token"}]},
            headers={"X-Ingest-Token": "invalid_wrong_token_999"},
        )
        assert resp.status_code == 403
        assert "Ingest Token không hợp lệ" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_02_extension_session_missing_xf_user_rejected():
    """2. Bắt buộc có xf_user: Chỉ gửi xf_session phải bị từ chối 400."""
    settings = get_settings()
    valid_token = settings.INGEST_TOKEN

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/auth/fuexam/extension-session",
            json={
                "cookies": [
                    {"name": "xf_session", "value": "some_session_value"},
                    {"name": "xf_csrf", "value": "csrf_123"},
                ]
            },
            headers={"X-Ingest-Token": valid_token},
        )
        assert resp.status_code == 400
        assert "Thiếu cookie xf_user" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_03_extension_session_empty_xf_user_rejected():
    """3. xf_user có giá trị rỗng -> Bị từ chối 400."""
    settings = get_settings()
    valid_token = settings.INGEST_TOKEN

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/auth/fuexam/extension-session",
            json={
                "cookies": [
                    {"name": "xf_user", "value": "   "},
                    {"name": "xf_session", "value": "session_val"},
                ]
            },
            headers={"X-Ingest-Token": valid_token},
        )
        assert resp.status_code == 400
        assert "Thiếu cookie xf_user" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_04_extension_session_probe_failure_not_saved():
    """4. Probe thất bại (trang web không trả về data-logged-in='true') -> 400, không lưu file."""
    settings = get_settings()
    valid_token = settings.INGEST_TOKEN
    auth_file = settings.DATA_DIR / "auth" / "fuexam_storage_state.json"
    user_file = settings.DATA_DIR / "auth" / "fuexam_user.json"

    # Mock requests.get trả về trang khách (chưa đăng nhập, không có data-logged-in="true")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = '<html data-logged-in="false"><body>Trang khach</body></html>'

    transport = ASGITransport(app=app)
    with patch("requests.get", return_value=mock_resp):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/auth/fuexam/extension-session",
                json={
                    "cookies": [
                        {"name": "xf_user", "value": "5300,expired_token"},
                        {"name": "xf_session", "value": "sess_123"},
                    ]
                },
                headers={"X-Ingest-Token": valid_token},
            )
            assert resp.status_code == 400
            assert "Phiên đăng nhập không hợp lệ" in resp.json()["detail"]
            assert not auth_file.exists(), "Không được lưu auth_file khi probe thất bại"
            assert not user_file.exists(), "Không được lưu user_file khi probe thất bại"


@pytest.mark.asyncio
async def test_05_extension_session_probe_success_saved():
    """5. Probe thành công -> 200, lưu fuexam_storage_state.json và fuexam_user.json với auth_source='extension'."""
    settings = get_settings()
    valid_token = settings.INGEST_TOKEN
    auth_file = settings.DATA_DIR / "auth" / "fuexam_storage_state.json"
    user_file = settings.DATA_DIR / "auth" / "fuexam_user.json"

    valid_html = """
    <!DOCTYPE html>
    <html data-logged-in="true">
    <head><title>fuexam.me</title></head>
    <body>
        <div class="p-navgroup p-account p-navgroup--member">
            <a href="/members/ong-khoi.5300/" class="p-navgroup-link p-navgroup-link--iconic p-navgroup-link--user">
                <span class="p-navgroup-linkText">Đông Khởi</span>
            </a>
        </div>
    </body>
    </html>
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = valid_html

    transport = ASGITransport(app=app)
    with patch("requests.get", return_value=mock_resp):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/auth/fuexam/extension-session",
                json={
                    "cookies": [
                        {"name": "xf_user", "value": "5300,valid_token_abc", "domain": ".fuexam.me"},
                        {"name": "xf_session", "value": "session_xyz", "domain": ".fuexam.me"},
                        {"name": "xf_csrf", "value": "csrf_123", "domain": ".fuexam.me"},
                    ]
                },
                headers={"X-Ingest-Token": valid_token},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert data["username"] == "Đông Khởi"

            # Kiểm tra file đã lưu
            assert auth_file.exists()
            assert user_file.exists()

            saved_user = json.loads(user_file.read_text(encoding="utf-8"))
            assert saved_user["username"] == "Đông Khởi"
            assert saved_user["auth_source"] == "extension"

            # Kiểm tra endpoint status trả auth_source="extension"
            status_resp = await client.get("/api/auth/fuexam/status")
            assert status_resp.status_code == 200
            st_data = status_resp.json()
            assert st_data["logged_in"] is True
            assert st_data["username"] == "Đông Khởi"
            assert st_data["auth_source"] == "extension"


@pytest.mark.asyncio
async def test_06_extension_session_no_cookie_values_logged(caplog):
    """6. Tuyệt đối không log bất kỳ giá trị cookie nhạy cảm nào vào log."""
    settings = get_settings()
    valid_token = settings.INGEST_TOKEN

    secret_user_token = "SUPER_SECRET_USER_TOKEN_99999"
    secret_session_token = "SUPER_SECRET_SESSION_TOKEN_88888"

    valid_html = """
    <html data-logged-in="true">
    <body>
        <div class="p-navgroup p-account p-navgroup--member">
            <span class="p-navgroup-linkText">Đông Khởi</span>
        </div>
    </body>
    </html>
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = valid_html

    transport = ASGITransport(app=app)
    with caplog.at_level(logging.DEBUG):
        with patch("requests.get", return_value=mock_resp):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/api/auth/fuexam/extension-session",
                    json={
                        "cookies": [
                            {"name": "xf_user", "value": secret_user_token},
                            {"name": "xf_session", "value": secret_session_token},
                        ]
                    },
                    headers={"X-Ingest-Token": valid_token},
                )
                assert resp.status_code == 200
                resp_text = resp.text

    # Không xuất hiện trong response
    assert secret_user_token not in resp_text
    assert secret_session_token not in resp_text

    # Không xuất hiện trong bất kỳ log record nào
    for record in caplog.records:
        assert secret_user_token not in record.message, f"Rò rỉ token người dùng trong log: {record.message}"
        assert secret_session_token not in record.message, f"Rò rỉ session token trong log: {record.message}"


@pytest.mark.asyncio
async def test_07_extension_logout_does_not_call_server():
    """
    7. Đăng xuất ở chế độ extension:
    - Chỉ xoá file cục bộ
    - KHÔNG được gọi POST /logout/ tới fuexam.me (tránh làm logout trình duyệt thật của user)
    """
    settings = get_settings()
    auth_file = settings.DATA_DIR / "auth" / "fuexam_storage_state.json"
    user_file = settings.DATA_DIR / "auth" / "fuexam_user.json"

    # Giả lập phiên có auth_source="extension"
    auth_file.parent.mkdir(parents=True, exist_ok=True)
    auth_file.write_text(json.dumps({"cookies": [{"name": "xf_user", "value": "test"}]}), encoding="utf-8")
    user_file.write_text(json.dumps({"username": "Đông Khởi", "auth_source": "extension"}), encoding="utf-8")

    transport = ASGITransport(app=app)
    with patch("requests.post") as mock_post, patch("requests.get") as mock_get:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/auth/fuexam/logout")
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert "không đăng xuất trình duyệt thật" in data["message"]

        # Khẳng định requests.post và requests.get KHÔNG BAO GIỜ bị gọi tới /logout/
        mock_post.assert_not_called()
        mock_get.assert_not_called()

    # File cục bộ đã bị xoá
    assert not auth_file.exists()
    assert not user_file.exists()

    # Trạng thái trở về logged_out
    logged_in, status_code, username, auth_source = _check_fuexam_auth_file()
    assert logged_in is False
    assert status_code == "logged_out"
    assert username is None
    assert auth_source is None
