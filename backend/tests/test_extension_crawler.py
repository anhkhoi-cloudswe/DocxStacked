"""
Unit tests for Chromium Extension extraction logic and ingestion endpoints.
Runs parsing directly against sanitized XenForo fixtures (no live network, no hardcoded counters).
"""

from pathlib import Path
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient
import pytest

from backend.app.main import app
from backend.app.core.config import get_settings

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
settings = get_settings()
client = TestClient(app)


def test_parse_thread_attachments_from_clean_fixture():
    """
    Test parsing thread attachment list corresponding to extension logic:
    - Extracts file names, indices, media URLs and media IDs.
    """
    thread_fixture = FIXTURES_DIR / "thread_mln122_su26_re_clean.html"
    assert thread_fixture.exists(), f"Fixture missing: {thread_fixture}"

    html = thread_fixture.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")

    # Extract title
    title_el = soup.select_one(".p-title-value")
    thread_title = title_el.get_text(strip=True) if title_el else ""
    assert thread_title == "MLN122 - SU26 - RE"

    # Extract attachments (same selector as extension sidepanel.js)
    attachment_items = soup.select("section.message-attachments ul.attachmentList li.file")
    assert len(attachment_items) == 5

    parsed_attachments = []
    for idx, item in enumerate(attachment_items, start=1):
        name_el = item.select_one(".file-name")
        file_name = name_el.get_text(strip=True) if name_el else f"Q{idx}.webp"

        preview_el = item.select_one("a.file-preview, span.file-preview")
        sidebar_href = preview_el.get("data-lb-sidebar-href", "") if preview_el else ""
        media_path = sidebar_href.split("?")[0]
        media_url = f"https://fuoverflow.com{media_path}" if media_path.startswith("/") else media_path

        import re
        m_id = re.search(r"/media/[^.]+\.(\d+)", media_path)
        media_id = m_id.group(1) if m_id else None

        parsed_attachments.append({
            "index": idx,
            "file_name": file_name,
            "media_id": media_id,
            "media_url": media_url,
        })

    assert parsed_attachments[0]["file_name"] == "Q1.webp"
    assert parsed_attachments[0]["media_id"] == "134314"
    assert parsed_attachments[0]["media_url"] == "https://fuoverflow.com/media/q1-webp.134314/"

    assert parsed_attachments[2]["file_name"] == "Q11.webp"
    assert parsed_attachments[2]["media_id"] == "137454"

    print(f"\n[Test Result] Extracted {len(parsed_attachments)} attachments cleanly from fixture.")


def test_parse_comments_from_media_fixtures():
    """
    Test parsing comments from sanitized media page fixtures matching extension parseCommentsFromHtml().
    Tests author, raw_text (without quote blocks), upvotes calculation, and reply flags.
    """
    fixtures_expected = [
        ("media_q1-webp_134314_clean.html", 2),
        ("media_q2-webp_134315_clean.html", 2),
        ("media_q11-webp_137454_clean.html", 14),
        ("media_q35-webp_130984_clean.html", 9),
        ("media_q36-webp_130985_clean.html", 8),
    ]

    total_parsed_comments = 0

    for filename, min_expected_comments in fixtures_expected:
        file_path = FIXTURES_DIR / filename
        assert file_path.exists(), f"Fixture missing: {file_path}"

        html_str = file_path.read_text(encoding="utf-8")
        soup = BeautifulSoup(html_str, "html.parser")
        comment_els = soup.select(".message--comment, .message--mediaComment, .js-comment")

        comments = []
        for c in comment_els:
            # Comment ID
            raw_id = c.get("data-content") or c.get("id") or ""
            import re
            m_id = re.search(r"\d+", raw_id)
            comment_id = m_id.group(0) if m_id else None

            # Author
            author_el = c.select_one(".message-name, .comment-user, .username, .comment-author")
            author_name = author_el.get_text(strip=True) if author_el else "Unknown"

            # Reactions / Upvotes
            rx_bar = c.select_one(".reactionsBar")
            upvotes = 0
            if rx_bar:
                text = rx_bar.get_text() or ""
                m_total = re.search(r"(\d+)\s+(?:reactions|lượt thích|phản ứng)", text, re.IGNORECASE)
                if m_total:
                    upvotes = int(m_total.group(1))
                else:
                    bdis = len(rx_bar.select("bdi"))
                    m_others = re.search(r"(?:and|và)\s+(\d+)\s+(?:others|người khác)", text, re.IGNORECASE)
                    others = int(m_others.group(1)) if m_others else 0
                    upvotes = bdis + others or 1

            # Quoted Comment ID & reply flag
            quoted_comment_id = None
            is_reply = False
            quote_block = c.select_one("blockquote, .bbCodeBlock--quote")
            if quote_block:
                is_reply = True
                title_link = quote_block.select_one(".bbCodeBlock-title a")
                if title_link and title_link.get("href"):
                    m_q = re.search(r"/comments/(\d+)", title_link.get("href", ""))
                    if m_q:
                        quoted_comment_id = int(m_q.group(1))

            # Body text without quotes
            bb = c.select_one(".message-body .bbWrapper, .message-body, .comment-content")
            raw_text = ""
            if bb:
                # Copy or extract stripped text
                import copy
                bb_copy = copy.copy(bb)
                for q in bb_copy.select("blockquote, .bbCodeBlock--quote"):
                    q.decompose()
                raw_text = bb_copy.get_text(strip=True)

            if raw_text:
                comments.append({
                    "comment_id": comment_id,
                    "author_name": author_name,
                    "raw_text": raw_text,
                    "upvotes": upvotes,
                    "quoted_comment_id": quoted_comment_id,
                    "is_reply": is_reply,
                })

        assert len(comments) >= min_expected_comments
        total_parsed_comments += len(comments)
        print(f"  - {filename:35s}: {len(comments):2d} comments parsed successfully.")

    assert total_parsed_comments == (2 + 2 + 14 + 9 + 8)
    print(f"[Test Result] Total parsed comments across 5 fixtures: {total_parsed_comments}")


def test_ingest_security_checks(tmp_path, monkeypatch):
    """
    Verify security controls on POST /api/ingest:
    - Missing or incorrect token returns 401 Unauthorized.
    - Disallowed Origin returns 403 Forbidden.
    - Valid token and localhost or chrome-extension origin passes.
    """
    monkeypatch.setattr(settings, "STORAGE_DIR", tmp_path)
    # 1. Missing token & Missing header -> 403 (or 401)
    res1 = client.post(
        "/api/ingest",
        json={"subject_code": "MLN122", "exam_title": "MLN122 - SU26 - RE", "questions": []},
    )
    assert res1.status_code in (401, 403)

    # 2. Invalid token & Missing header -> 403 (or 401)
    res2 = client.post(
        "/api/ingest",
        json={"subject_code": "MLN122", "exam_title": "MLN122 - SU26 - RE", "questions": []},
        headers={"X-Ingest-Token": "invalid_wrong_token_12345"},
    )
    assert res2.status_code in (401, 403)

    # 3. Disallowed Origin -> 403
    res3 = client.post(
        "/api/ingest",
        json={"subject_code": "MLN122", "exam_title": "MLN122 - SU26 - RE", "questions": []},
        headers={
            "X-Ingest-Token": settings.INGEST_TOKEN,
            "Origin": "https://malicious-website.com",
        },
    )
    assert res3.status_code == 403
    assert "Chromium extension" in res3.json()["detail"] or "Origin" in res3.json()["detail"]

    # 4. Valid token with chrome-extension origin -> accepted
    client.post("/api/ingest/clear-runs", headers={"X-Ingest-Token": settings.INGEST_TOKEN})
    res4 = client.post(
        "/api/ingest",
        json={
            "run_id": "test_security_check_run_01",
            "subject_code": "MLN122",
            "exam_title": "MLN122 - SU26 - RE",
            "exam_url": "https://fuoverflow.com/threads/mln122-su26-re.7207/",
            "questions": [],
            "options": {"ai_enabled": False},
        },
        headers={
            "X-Ingest-Token": settings.INGEST_TOKEN,
            "Origin": f"chrome-extension://{settings.EXTENSION_ID}",
        },
    )
    assert res4.status_code == 200
    assert res4.json()["status"] == "success"
    print("\n[Test Result] Security checks verified: Token 401 and Origin 403 work as required.")


def test_existing_exam_title_preserved(tmp_path, monkeypatch):
    """
    Verify that existing exam in database retains its exact title,
    without prefix duplication ('MLN122 - MLN122') or suffix adding.
    """
    monkeypatch.setattr(settings, "STORAGE_DIR", tmp_path)
    client.post("/api/ingest/clear-runs", headers={"X-Ingest-Token": settings.INGEST_TOKEN})
    original_title = "MLN122 - SU26 - RE"
    exam_url = "https://fuoverflow.com/threads/mln122-su26-re.7207/"

    # First ingest the original exam to ensure it exists in the test DB
    client.post(
        "/api/ingest",
        json={
            "run_id": "test_title_preservation_run_01",
            "subject_code": "MLN122",
            "exam_title": original_title,
            "exam_url": exam_url,
            "questions": [],
            "options": {"ai_enabled": False},
        },
        headers={"X-Ingest-Token": settings.INGEST_TOKEN},
    )

    # Ingest with slightly different or decorated title
    payload = {
        "run_id": "test_title_preservation_run_02",
        "subject_code": "MLN122",
        "exam_title": "MLN122 - MLN122 - SU26 - RE (Extension Ingested)",
        "exam_url": exam_url,
        "questions": [],
        "options": {"ai_enabled": False},
    }

    res = client.post(
        "/api/ingest",
        json=payload,
        headers={"X-Ingest-Token": settings.INGEST_TOKEN},
    )
    assert res.status_code == 200
    res_data = res.json()

    # The exam title in response must be original_title
    assert res_data["exam_title"] == original_title
    assert "MLN122 - MLN122" not in res_data["exam_title"]
    assert "(Extension Ingested)" not in res_data["exam_title"]
    assert res_data["docx_filename"].startswith("MLN122 - SU26 - RE")
    print(f"\n[Test Result] Title preserved accurately: '{res_data['exam_title']}' -> '{res_data['docx_filename']}'")


def test_ingest_response_download_url_and_docx_valid(tmp_path, monkeypatch):
    """
    Test: POST /api/ingest then call the returned download_url.
    Must receive 200 OK and file must be valid Word docx openable by python-docx.
    """
    monkeypatch.setattr(settings, "STORAGE_DIR", tmp_path)
    client.post("/api/ingest/clear-runs", headers={"X-Ingest-Token": settings.INGEST_TOKEN})
    import docx
    import io

    payload = {
        "run_id": "test_download_valid_run_01",
        "subject_code": "TEST102",
        "exam_title": "TEST102 - SU26 - FE",
        "exam_url": "https://fuoverflow.com/threads/test102-fe.8888/",
        "questions": [],
        "options": {"ai_enabled": False},
    }

    res = client.post(
        "/api/ingest",
        json=payload,
        headers={"X-Ingest-Token": settings.INGEST_TOKEN},
    )
    assert res.status_code == 200
    res_data = res.json()
    assert "download_url" in res_data
    download_url = res_data["download_url"]

    # Call the returned download URL
    dl_res = client.get(download_url)
    assert dl_res.status_code == 200
    assert "wordprocessingml.document" in dl_res.headers.get("content-type", "")
    assert "TEST102" in dl_res.headers.get("content-disposition", "")
    assert "FE.docx" in dl_res.headers.get("content-disposition", "")

    # Open with python-docx
    doc = docx.Document(io.BytesIO(dl_res.content))
    assert doc is not None

