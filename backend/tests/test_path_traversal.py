"""
backend/tests/test_path_traversal.py - Path Traversal Security Test Suite.
Verifies that download and delete endpoints strictly reject any attempt to access
or delete files outside the data/output directory (e.g. cookies.json, databases, parent paths).
"""

from pathlib import Path
import pytest
from httpx import AsyncClient, ASGITransport

from backend.app.core.config import get_settings
from backend.app.db.session import init_db
from backend.app.main import app

settings = get_settings()


@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()


@pytest.mark.asyncio
async def test_download_prevents_path_traversal_to_cookies():
    """Attempting to download data/auth/cookies.json via path traversal must return HTTP 403."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Traversal from output directory to auth/cookies.json
        resp = await client.get("/api/exports/download", params={"path": "../auth/cookies.json"})
        assert resp.status_code == 403
        assert "Access denied" in resp.json()["detail"]

        # Absolute or relative to base
        resp2 = await client.get("/api/exports/download", params={"file": "data/auth/cookies.json"})
        assert resp2.status_code == 403


@pytest.mark.asyncio
async def test_download_prevents_traversal_to_system_files():
    """Attempting to download system files or parent folders must return HTTP 403."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for payload in [
            "../../../../etc/passwd",
            "..\\..\\..\\windows\\system32\\drivers\\etc\\hosts",
            "../.env",
            "data/docxstacked.db",
        ]:
            resp = await client.get("/api/exports/download", params={"path": payload})
            assert resp.status_code == 403, f"Failed to reject traversal payload: {payload}"


@pytest.mark.asyncio
async def test_delete_prevents_path_traversal():
    """Attempting to delete files outside data/output must return HTTP 403."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for payload in [
            "data/auth/cookies.json",
            "../auth/cookies.json",
            "../../.env",
            "data/docxstacked.db",
        ]:
            resp = await client.delete("/api/user/documents", params={"file": payload})
            assert resp.status_code == 403, f"Failed to reject delete traversal payload: {payload}"


@pytest.mark.asyncio
async def test_download_and_delete_allowed_inside_output_dir(tmp_path):
    """Files legitimately created inside data/output can be safely downloaded and deleted."""
    out_dir = settings.OUTPUT_DIR / "TEST_SEC"
    out_dir.mkdir(parents=True, exist_ok=True)
    test_file = out_dir / "safe_document.docx"
    test_file.write_bytes(b"PK\x03\x04test_safe_docx_content")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Download safe file
        resp = await client.get("/api/exports/download", params={"file": "data/output/TEST_SEC/safe_document.docx"})
        assert resp.status_code == 200
        assert resp.content == b"PK\x03\x04test_safe_docx_content"

        # Delete safe file
        del_resp = await client.delete("/api/user/documents", params={"file": "data/output/TEST_SEC/safe_document.docx"})
        assert del_resp.status_code == 200
        assert not test_file.exists()
