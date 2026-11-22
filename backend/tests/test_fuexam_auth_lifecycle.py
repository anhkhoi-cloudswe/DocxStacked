"""
backend/tests/test_fuexam_auth_lifecycle.py
Kiểm thử chu trình xác thực fuexam theo đúng 6 yêu cầu:
1. Đăng xuất: xoá storage_state.json, profile Chromium, gọi server-side logout.
   /api/auth/fuexam/status phải trả logged_out.
2. Mỗi lần đăng nhập mở Chromium mới, không profile cũ, không nạp storage_state cũ.
3. Điều kiện thành công phải đồng thời: có xf_user (không chấp nhận chỉ xf_session)
   VÀ request trang công khai trả về html[data-logged-in="true"]. Chờ tối đa 5 phút.
4. Hiện tên tài khoản thật (Đông Khởi) trên header, không hiện cookie hay token.
5. Backend khởi chạy Chromium trực tiếp (creationflags=0), không nháy cmd console.
6. Luồng từ chối đề: chưa đăng nhập -> gọi đề bị từ chối 401 -> sau khi đăng nhập -> cho phép.
"""

import json
from pathlib import Path
import pytest
from httpx import AsyncClient, ASGITransport

from backend.app.main import app
from backend.app.core.config import get_settings
from backend.app.api.auth import _check_fuexam_auth_file, _perform_fuexam_logout_sync
from scripts.fuexam_login import (
    extract_real_username_from_html,
    verify_public_page_logged_in,
    check_status,
)


@pytest.mark.asyncio
async def test_01_logout_deletes_all_storage_and_profiles():
    """Yêu cầu 1: Đăng xuất xoá storage_state.json, xoá mọi thư mục profile Chromium, status=logged_out."""
    settings = get_settings()
    auth_file = settings.DATA_DIR / "auth" / "fuexam_storage_state.json"
    user_file = settings.DATA_DIR / "auth" / "fuexam_user.json"
    profile_dir = settings.DATA_DIR / "browser_profile_fuexam"

    # Tạo tệp và thư mục giả lập tồn tại trước đó
    auth_file.parent.mkdir(parents=True, exist_ok=True)
    auth_file.write_text(json.dumps({"cookies": [{"name": "xf_user", "value": "test"}]}), encoding="utf-8")
    user_file.write_text(json.dumps({"username": "TestUser"}), encoding="utf-8")
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / "cache.bin").write_text("data", encoding="utf-8")

    # Thực hiện đăng xuất
    success, msg = _perform_fuexam_logout_sync()
    assert success is True

    # Khẳng định tệp và thư mục đã bị xoá hoàn toàn
    assert not auth_file.exists(), "storage_state.json phải bị xoá"
    assert not user_file.exists(), "fuexam_user.json phải bị xoá"
    assert not profile_dir.exists(), "browser_profile_fuexam phải bị xoá sạch"

    # Trạng thái status phải trả logged_out
    logged_in, status_code, username = _check_fuexam_auth_file()
    assert logged_in is False
    assert status_code == "logged_out"
    assert username is None

    # Gọi endpoint /api/auth/fuexam/status
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/auth/fuexam/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["logged_in"] is False
        assert data["status_code"] == "logged_out"
        assert data["username"] is None


@pytest.mark.asyncio
async def test_02_job_creation_rejected_when_logged_out():
    """Yêu cầu 6 (bước 3): Khi chưa đăng nhập, gọi đề fuexam phải bị từ chối 401."""
    # Đảm bảo đã logged_out
    _perform_fuexam_logout_sync()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/jobs", json={
            "platform": "fuexam",
            "thread_id": 1174,
            "subject_code": "PRM393",
            "exam_name": "PRM393 - SU26 - B5 - FE",
            "exam_type": "FE",
        })
        assert resp.status_code == 401
        assert "Cần đăng nhập fuexam.me" in resp.json()["detail"]


def test_03_dual_condition_xf_user_and_public_page():
    """
    Yêu cầu 3: Điều kiện thành công phải đồng thời:
    - có cookie xf_user (không chấp nhận chỉ xf_session)
    - html[data-logged-in="true"] trên trang công khai.
    """
    settings = get_settings()
    auth_file = settings.DATA_DIR / "auth" / "fuexam_storage_state.json"

    # Trường hợp 1: Chỉ có xf_session, KHÔNG có xf_user -> BỊ TỪ CHỐI
    auth_file.write_text(json.dumps({
        "cookies": [
            {"name": "xf_session", "value": "some_session_token", "domain": "fuexam.me"}
        ]
    }), encoding="utf-8")
    logged_in, status_code, _ = _check_fuexam_auth_file()
    assert logged_in is False, "Chỉ có xf_session không được chấp nhận đăng nhập"
    assert status_code == "logged_out"

    # Trường hợp 2: Có xf_user nhưng rỗng -> BỊ TỪ CHỐI
    auth_file.write_text(json.dumps({
        "cookies": [
            {"name": "xf_user", "value": "", "domain": "fuexam.me"}
        ]
    }), encoding="utf-8")
    logged_in, status_code, _ = _check_fuexam_auth_file()
    assert logged_in is False
    assert status_code == "logged_out"

    # Dọn dẹp
    auth_file.unlink(missing_ok=True)


def test_04_real_username_extraction_from_html():
    """Yêu cầu 4: Trích xuất tên tài khoản thật từ HTML (Đông Khởi), không dùng chuỗi cố định."""
    sample_xenforo_html = """
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
    username = extract_real_username_from_html(sample_xenforo_html)
    assert username == "Đông Khởi", f"Trích xuất tên thật thất bại, nhận được: {username}"


@pytest.mark.asyncio
async def test_05_header_renders_real_username_no_leaked_tokens():
    """Yêu cầu 4: Khi đăng nhập thành công, username thật hiển thị, không lộ cookie hay token."""
    settings = get_settings()
    auth_file = settings.DATA_DIR / "auth" / "fuexam_storage_state.json"
    user_file = settings.DATA_DIR / "auth" / "fuexam_user.json"

    # Giả lập trạng thái đã đăng nhập với tên thật "Đông Khởi"
    auth_file.write_text(json.dumps({
        "cookies": [
            {"name": "xf_user", "value": "5300,valid_token_sample", "domain": "fuexam.me"}
        ]
    }), encoding="utf-8")
    user_file.write_text(json.dumps({
        "username": "Đông Khởi",
        "logged_in_at": "2026-11-22T14:00:00",
    }), encoding="utf-8")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/auth/fuexam/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["logged_in"] is True
        assert data["status_code"] == "logged_in"
        assert data["username"] == "Đông Khởi"
        # Tuyệt đối không chứa chuỗi cookie nhạy cảm hay token
        assert "valid_token_sample" not in json.dumps(data)
        assert "5300" not in data["username"]

    # Dọn dẹp
    auth_file.unlink(missing_ok=True)
    user_file.unlink(missing_ok=True)
