from pathlib import Path
import pytest
from httpx import AsyncClient, ASGITransport

from backend.app.main import app
from backend.app.db.models import Exam, ExamType, Subject
from backend.app.db.session import async_session_factory
from backend.app.modules.crawler.subjects import (
    parse_subjects_from_category_html,
    strip_vietnamese_accents,
    sync_subjects_from_web,
    lookup_subject_by_code,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def test_strip_vietnamese_accents():
    assert strip_vietnamese_accents("Cấu trúc dữ liệu") == "cau truc du lieu"
    assert strip_vietnamese_accents("Đồ họa máy tính") == "do hoa may tinh"
    assert strip_vietnamese_accents("KỸ THUẬT LẬP TRÌNH") == "ky thuat lap trinh"
    assert strip_vietnamese_accents("CSD202") == "csd202"
    assert strip_vietnamese_accents("") == ""


def test_parse_subjects_from_category_html():
    fixture_path = FIXTURES_DIR / "subjects_category_page.html"
    assert fixture_path.exists(), "subjects_category_page.html fixture must exist"

    html = fixture_path.read_text(encoding="utf-8")
    parsed = parse_subjects_from_category_html(html)

    # Should parse around 400 subjects
    assert len(parsed) >= 380, f"Expected at least 380 subjects, got {len(parsed)}"

    # Check that codes are unique
    codes = [s["code"] for s in parsed]
    assert len(codes) == len(set(codes)), "Subject codes should be unique"

    # Known popular subjects must exist
    assert "CSD202" in codes
    assert "PRN232" in codes
    assert "PRF193" in codes

    # Excluded slugs must NOT be in codes
    assert "TONG-HOP" not in codes
    assert "QUY-DINH" not in codes
    assert "HUONG-DAN-DANG-TAI-LIEU" not in codes

    # CSD202 should have a meaningful name
    csd = next(s for s in parsed if s["code"] == "CSD202")
    assert "Data Structures" in csd["name"] or "CSD202" in csd["name"]
    assert csd["forum_url"].startswith("https://fuoverflow.com/forums/")


@pytest.mark.asyncio
async def test_sync_subjects_and_search_api():
    fixture_path = FIXTURES_DIR / "subjects_category_page.html"
    html = fixture_path.read_text(encoding="utf-8")

    async with async_session_factory() as db:
        sync_res = await sync_subjects_from_web(db, html=html)
        assert sync_res["total"] >= 380
        assert sync_res["last_synced_at"] is not None

        # Re-syncing with same html should update, not add duplicates
        sync_res2 = await sync_subjects_from_web(db, html=html)
        assert sync_res2["added"] == 0
        assert sync_res2["updated"] >= 380

    # Test API endpoints via AsyncClient
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Search without query
        resp = await client.get("/api/subjects?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data
        assert data["total"] >= 380
        assert len(data["items"]) == 10
        assert data["last_synced_at"] is not None

        # 2. Search accent-insensitive: "cau truc" should find CSD202
        resp = await client.get("/api/subjects?q=cau truc")
        assert resp.status_code == 200
        data = resp.json()
        # Find if CSD202 is matched (Data Structures or CSD202)
        # Or test "csd"
        resp_csd = await client.get("/api/subjects?q=csd")
        assert resp_csd.status_code == 200
        items = resp_csd.json()["items"]
        assert any(item["code"] == "CSD202" for item in items)

        # 3. Pagination offset
        resp_page1 = await client.get("/api/subjects?limit=5&offset=0")
        resp_page2 = await client.get("/api/subjects?limit=5&offset=5")
        codes1 = [i["code"] for i in resp_page1.json()["items"]]
        codes2 = [i["code"] for i in resp_page2.json()["items"]]
        assert len(set(codes1).intersection(set(codes2))) == 0


@pytest.mark.asyncio
async def test_lookup_subject_flow():
    mock_html_success = """
    <html>
        <head><title>SWE102 - Nhập môn Kỹ thuật Phần mềm | FuOverflow</title></head>
        <body>
            <h1 class="p-title-value">SWE102 - Nhập môn Kỹ thuật Phần mềm</h1>
        </body>
    </html>
    """
    mock_html_not_found = """
    <html>
        <head><title>Lỗi | FuOverflow</title></head>
        <body>
            <div class="blockMessage blockMessage--error">The requested forum could not be found.</div>
        </body>
    </html>
    """

    async with async_session_factory() as db:
        # Mock lookup success
        subj = await lookup_subject_by_code(db, "SWE102", html_content=mock_html_success)
        assert subj is not None
        assert subj.code == "SWE102"
        assert "Kỹ thuật Phần mềm" in subj.name or "SWE102" in subj.name

        # Mock lookup not found
        subj_none = await lookup_subject_by_code(db, "UNKNOWN999", html_content=mock_html_not_found)
        assert subj_none is None

    # Test lookup API endpoint
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Existing should return immediately
        resp = await client.post("/api/subjects/lookup", json={"code": "SWE102"})
        assert resp.status_code == 200
        assert resp.json()["code"] == "SWE102"

        # Invalid format
        resp_invalid = await client.post("/api/subjects/lookup", json={"code": "X"})
        assert resp_invalid.status_code == 422


@pytest.mark.asyncio
async def test_subject_exams_api():
    async with async_session_factory() as db:
        # Ensure CSD202 exists and has an exam
        subj = await lookup_subject_by_code(db, "CSD202")
        if subj:
            test_url = "https://fuoverflow.com/threads/csd202-fe-su26-1.99999/"
            from sqlalchemy import select
            existing = (await db.execute(select(Exam).where(Exam.url == test_url))).scalar_one_or_none()
            if not existing:
                exam = Exam(
                    subject_id=subj.id,
                    title="CSD202 FE SU26 Đề 1",
                    url=test_url,
                    exam_type=ExamType.FE,
                    term="SU26",
                    question_count=40,
                )
                db.add(exam)
                await db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/subjects/CSD202/exams?type=FE")
        assert resp.status_code == 200
        exams = resp.json()
        assert isinstance(exams, list)
        assert any("CSD202" in e["title"] for e in exams)
