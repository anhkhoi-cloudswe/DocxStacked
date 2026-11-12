import io
import zipfile
import pytest
from httpx import ASGITransport, AsyncClient
from backend.app.api.exports import parse_subject_and_category
from backend.app.core.config import get_settings
from backend.app.main import app

settings = get_settings()


def test_parse_subject_and_category():
    # FE and RE are grouped together under FE
    sub, cat = parse_subject_and_category("PRM392 - SP26 - RE.docx")
    assert sub == "PRM392"
    assert cat == "FE"

    sub, cat = parse_subject_and_category("PRM392 - SP 2024 - FE.docx")
    assert sub == "PRM392"
    assert cat == "FE"

    sub, cat = parse_subject_and_category("PRM392 - Retake - SP24.docx")
    assert sub == "PRM392"
    assert cat == "FE"

    # PE is separate under PE
    sub, cat = parse_subject_and_category("PRM392 - SU26 - PE.zip")
    assert sub == "PRM392"
    assert cat == "PE"

    sub, cat = parse_subject_and_category("CSD202 - SU26 - FE.docx")
    assert sub == "CSD202"
    assert cat == "FE"


@pytest.mark.asyncio
async def test_download_folder_zip_structure(tmp_path):
    # Setup dummy docx files in output dir
    out_dir = settings.OUTPUT_DIR / "TEST_SUBJ"
    out_dir.mkdir(parents=True, exist_ok=True)
    f1 = out_dir / "TEST_SUBJ - SP26 - RE.docx"
    f2 = out_dir / "TEST_SUBJ - SP26 - FE.docx"
    f1.write_bytes(b"dummy content 1")
    f2.write_bytes(b"dummy content 2")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/exports/download-folder?subject=TEST_SUBJ")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"
        assert "TEST_SUBJ_FE.zip" in resp.headers["content-disposition"]

        # Verify zip contents and directory structure
        zf = zipfile.ZipFile(io.BytesIO(resp.content))
        names = zf.namelist()
        assert "TEST_SUBJ_FE/TEST_SUBJ - SP26 - RE.docx" in names
        assert "TEST_SUBJ_FE/TEST_SUBJ - SP26 - FE.docx" in names

    # Clean up test files
    f1.unlink(missing_ok=True)
    f2.unlink(missing_ok=True)
    try:
        out_dir.rmdir()
    except Exception:
        pass
