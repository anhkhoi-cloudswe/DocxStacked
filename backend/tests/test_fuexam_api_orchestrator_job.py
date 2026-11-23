"""
Integration test for _run_fuexam_job_pipeline directly executed via POST /api/jobs.
Tests:
1. 2 threads with same subject/term/type but different suffixes (C1 and C2) produce:
   - MLN122 - FUE - FA26 - FE - C1.docx
   - MLN122 - FUE - FA26 - FE - C2.docx
   - Distinct .meta.json files with correct thread_id and stats
   - Thread titles used directly without overwrite
2. Fails cleanly with clear validation error when term cannot be determined (no guessed default).
3. Verifies orchestrator has zero undefined names and succeeds through full pipeline.
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
from PIL import Image
import pytest
from httpx import AsyncClient, ASGITransport

from backend.app.modules.analysis.ai_check import AIQuestionAnalysis
from backend.app.modules.export.image_cropper import CropResult
from backend.app.main import app
from backend.app.core.config import get_settings
from backend.app.db.session import init_db
from backend.app.modules.jobs.orchestrator import get_orchestrator


@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()


@pytest.mark.asyncio
async def test_fuexam_orchestrator_via_post_jobs_c1_c2(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "BASE_DIR", tmp_path)
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path / "data" / "output")
    monkeypatch.setattr("backend.app.modules.jobs.orchestrator.settings.BASE_DIR", tmp_path)
    monkeypatch.setattr("backend.app.modules.export.docx_builder.settings.BASE_DIR", tmp_path)
    
    # 1. Setup mock auth file
    auth_dir = settings.DATA_DIR / "auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    auth_file = auth_dir / "fuexam_storage_state.json"
    auth_file.write_text(json.dumps({
        "cookies": [
            {"name": "xf_user", "value": "mock_xf_user_val"},
            {"name": "xf_session", "value": "mock_xf_session_val"}
        ]
    }), encoding="utf-8")

    # 2. Setup mock question image
    img_dir = tmp_path / "mock_images"
    img_dir.mkdir(parents=True, exist_ok=True)
    sample_img = img_dir / "sample.png"
    im = Image.new("RGB", (300, 150), color=(240, 240, 240))
    im.save(sample_img)

    # 3. Mocks for crawler
    def mock_extract_thread(url, session):
        if "1473" in url:
            title = "MLN122 - FA26 - FE - C1 | FuExam"
            q_list = [
                {"index": 1, "title": "Câu 1", "slug": "q1", "media_id": 1001, "attachment_id": 2001, "attachment_url": "http://fuexam.me/att/1", "media_url": "http://fuexam.me/media/q1.1001/"},
                {"index": 2, "title": "Câu 2", "slug": "q2", "media_id": 1002, "attachment_id": 2002, "attachment_url": "http://fuexam.me/att/2", "media_url": "http://fuexam.me/media/q2.1002/"},
            ]
            return title, q_list
        elif "1474" in url:
            title = "MLN122 - FA26 - FE - C2 | FuExam"
            q_list = [
                {"index": 1, "title": "Câu 1", "slug": "q1", "media_id": 2001, "attachment_id": 3001, "attachment_url": "http://fuexam.me/att/3", "media_url": "http://fuexam.me/media/q1.2001/"},
                {"index": 2, "title": "Câu 2", "slug": "q2", "media_id": 2002, "attachment_id": 3002, "attachment_url": "http://fuexam.me/att/4", "media_url": "http://fuexam.me/media/q2.2002/"},
            ]
            return title, q_list
        elif "9999" in url:
            # Thread with no parseable term
            return "MLN122 - FE - NO_TERM | FuExam", [
                {"index": 1, "title": "Câu 1", "slug": "q1", "media_id": 9001, "attachment_id": 9001, "attachment_url": "http://fuexam.me/att/9", "media_url": "http://fuexam.me/media/q1.9001/"}
            ]
        return "Unknown Thread", []

    def mock_fetch_image(*args, **kwargs):
        return sample_img, True

    def mock_crop(img_path, output_path=None, **kwargs):
        dest = Path(output_path) if output_path else Path(img_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        im.save(dest)
        return CropResult(
            cropped_image=im,
            box=(0, 0, 300, 150),
            layout="fuexam_2026",
            output_path=dest,
        )

    def mock_fetch_comments(*args, **kwargs):
        return [
            {"username": "student_a", "comment_text": "1A", "reaction_score": 3},
            {"username": "student_b", "comment_text": "1A", "reaction_score": 1},
        ], True

    # Patch crawler and AI functions
    with patch("backend.app.modules.crawler.fuexam_crawler.get_authenticated_session", return_value=MagicMock()), \
         patch("backend.app.modules.crawler.fuexam_crawler.check_session_validity", return_value=True), \
         patch("backend.app.modules.crawler.fuexam_crawler.extract_thread_questions", side_effect=mock_extract_thread), \
         patch("backend.app.modules.crawler.fuexam_crawler.fetch_and_cache_media_image", side_effect=mock_fetch_image), \
         patch("backend.app.modules.crawler.fuexam_crawler.fetch_and_cache_media_comments", side_effect=mock_fetch_comments), \
         patch("backend.app.modules.export.image_cropper.crop_question_single", side_effect=mock_crop), \
         patch("backend.app.modules.analysis.ai_check.AICheckService.analyze_question_ensemble", return_value=[AIQuestionAnalysis(answers=["A"], confidence=0.95, provider="gemini", options={"A": "Option A"})]):

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Part 1: Run 2 threads C1 and C2 via POST /api/jobs
            resp = await client.post("/api/jobs", json={
                "subject_code": "MLN122",
                "exam_type": "FE",
                "limit": 2,
                "platform": "fuexam",
                "exam_ids": [1473, 1474],
                "exam_titles": {
                    "1473": "MLN122 - FA26 - FE - C1",
                    "1474": "MLN122 - FA26 - FE - C2"
                }
            })
            assert resp.status_code == 200, resp.text
            job_data = resp.json()
            job_id = job_data["job_id"]

            orchestrator = get_orchestrator()
            task = orchestrator._running_tasks.get(job_id)
            assert task is not None
            await task

            # Check status
            status_resp = await client.get(f"/api/jobs/{job_id}")
            assert status_resp.status_code == 200
            res_json = status_resp.json()
            assert res_json["status"] == "completed", f"Job failed: {res_json.get('error_message')}"

            # Check produced files
            files = res_json["details"].get("files", [])
            assert len(files) == 2, f"Expected 2 files, got: {files}"

            file_names = [Path(f["path"]).name for f in files]
            assert "MLN122 - FUE - FA26 - FE - C1.docx" in file_names
            assert "MLN122 - FUE - FA26 - FE - C2.docx" in file_names

            # Verify meta files exist and have distinct thread_ids and titles
            c1_file = next(f for f in files if "C1" in f["path"])
            c2_file = next(f for f in files if "C2" in f["path"])

            c1_path = tmp_path / c1_file["path"]
            c2_path = tmp_path / c2_file["path"]
            assert c1_path.exists()
            assert c2_path.exists()

            c1_meta = json.loads(Path(str(c1_path) + ".meta.json").read_text(encoding="utf-8"))
            c2_meta = json.loads(Path(str(c2_path) + ".meta.json").read_text(encoding="utf-8"))

            assert c1_meta["thread_id"] == 1473
            assert c2_meta["thread_id"] == 1474
            assert c1_meta["exam_title"] == "MLN122 - FA26 - FE - C1"
            assert c2_meta["exam_title"] == "MLN122 - FA26 - FE - C2"
            assert c1_meta["term"] == "FA26"
            assert c2_meta["term"] == "FA26"

            # Part 2: Test stopping cleanly when term cannot be determined (Requirement 3)
            no_term_resp = await client.post("/api/jobs", json={
                "subject_code": "MLN122",
                "exam_type": "FE",
                "limit": 1,
                "platform": "fuexam",
                "exam_ids": [9999],
                "exam_titles": {
                    "9999": "MLN122 - FE - NO_TERM"
                }
            })
            assert no_term_resp.status_code == 200
            no_term_job_id = no_term_resp.json()["job_id"]

            no_term_task = orchestrator._running_tasks.get(no_term_job_id)
            assert no_term_task is not None
            await no_term_task

            no_term_status_resp = await client.get(f"/api/jobs/{no_term_job_id}")
            assert no_term_status_resp.status_code == 200
            no_term_data = no_term_status_resp.json()
            assert no_term_data["status"] == "failed"
            assert "Không thể phân tích kỳ học" in no_term_data["error_message"]
            assert no_term_data["details"].get("is_retryable") is False


@pytest.mark.asyncio
async def test_orchestrator_formats_internal_errors_with_code(tmp_path, monkeypatch):
    """
    Test Requirement 4: Internal errors are displayed as friendly message with code:
    'Có lỗi nội bộ khi soạn đề, mã lỗi XYZ, xem log' and is_retryable=False.
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "BASE_DIR", tmp_path)
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "OUTPUT_DIR", tmp_path / "data" / "output")
    monkeypatch.setattr("backend.app.modules.jobs.orchestrator.settings.BASE_DIR", tmp_path)
    monkeypatch.setattr("backend.app.modules.export.docx_builder.settings.BASE_DIR", tmp_path)

    auth_dir = settings.DATA_DIR / "auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    auth_file = auth_dir / "fuexam_storage_state.json"
    auth_file.write_text(json.dumps({
        "cookies": [{"name": "xf_user", "value": "mock_val"}]
    }), encoding="utf-8")

    def mock_broken_extract(url, session):
        raise NameError("name 'undefined_symbol' is not defined")

    with patch("backend.app.modules.crawler.fuexam_crawler.get_authenticated_session", return_value=MagicMock()), \
         patch("backend.app.modules.crawler.fuexam_crawler.check_session_validity", return_value=True), \
         patch("backend.app.modules.crawler.fuexam_crawler.extract_thread_questions", side_effect=mock_broken_extract):

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/jobs", json={
                "subject_code": "MLN122",
                "exam_type": "FE",
                "limit": 1,
                "platform": "fuexam",
                "exam_ids": [1473],
                "exam_titles": {"1473": "MLN122 - FA26 - FE - C1"}
            })
            assert resp.status_code == 200
            job_id = resp.json()["job_id"]

            orchestrator = get_orchestrator()
            task = orchestrator._running_tasks.get(job_id)
            assert task is not None
            await task

            status_resp = await client.get(f"/api/jobs/{job_id}")
            assert status_resp.status_code == 200
            data = status_resp.json()
            assert data["status"] == "failed"
            # Must be friendly message with error code, no raw traceback
            assert "Có lỗi nội bộ khi soạn đề, mã lỗi ERR-" in data["error_message"]
            assert "undefined_symbol" not in data["error_message"]
            assert data["details"].get("is_retryable") is False
            assert data["details"].get("error_code", "").startswith("ERR-")

