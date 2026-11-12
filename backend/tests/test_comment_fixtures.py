"""
backend/tests/test_comment_fixtures.py - Tests for parsing real comment fixtures captured in Phase 0.5.
"""

from pathlib import Path
import re
import yaml
import pytest
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = BASE_DIR / "backend" / "config" / "selectors.yaml"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

@pytest.fixture
def selectors():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def test_fixture_files_exist():
    """Verify all 5 cleaned fixtures exist in backend/tests/fixtures/."""
    expected = [
        "media_q1-webp_134314_clean.html",
        "media_q2-webp_134315_clean.html",
        "media_q11-webp_137454_clean.html",
        "media_q35-webp_130984_clean.html",
        "media_q36-webp_130985_clean.html",
    ]
    for fn in expected:
        path = FIXTURES_DIR / fn
        assert path.exists(), f"Missing fixture {fn}"
        assert path.stat().st_size > 50000, f"Fixture {fn} is too small"

def test_parse_comments_vnr202_q11(selectors):
    """Test extracting comments from media_q11-webp_137454_clean.html (14 comments)."""
    fixture = FIXTURES_DIR / "media_q11-webp_137454_clean.html"
    soup = BeautifulSoup(fixture.read_text(encoding="utf-8"), "html.parser")

    comments = soup.select(selectors["comments"]["item"])
    assert len(comments) == 14, f"Expected 14 comments, got {len(comments)}"

    # Test individual comment fields
    c1 = comments[0]
    author = c1.select_one(selectors["comments"]["author"]).get_text(strip=True)
    body = c1.select_one(selectors["comments"]["text"]).get_text(strip=True)
    time_el = c1.select_one(selectors["comments"]["timestamp"])

    assert author.startswith("Student_"), "Author should be sanitized"
    assert body.lower() == "b", f"Expected body 'b', got '{body}'"
    assert time_el is not None
    assert "2026-08-12" in time_el.get("datetime", "")

def test_parse_comments_swd392_q35(selectors):
    """Test extracting comments from media_q35-webp_130984_clean.html (9 comments)."""
    fixture = FIXTURES_DIR / "media_q35-webp_130984_clean.html"
    soup = BeautifulSoup(fixture.read_text(encoding="utf-8"), "html.parser")

    comments = soup.select(selectors["comments"]["item"])
    assert len(comments) == 9, f"Expected 9 comments, got {len(comments)}"

    answers = [c.select_one(selectors["comments"]["text"]).get_text(strip=True).upper() for c in comments]
    # Answers contain B
    assert "B" in answers

def test_parse_comments_csd202_q1(selectors):
    """Test extracting comments from media_q1-webp_134314_clean.html (2 comments)."""
    fixture = FIXTURES_DIR / "media_q1-webp_134314_clean.html"
    soup = BeautifulSoup(fixture.read_text(encoding="utf-8"), "html.parser")

    comments = soup.select(selectors["comments"]["item"])
    assert len(comments) == 2, f"Expected 2 comments, got {len(comments)}"

    # First comment is 'a'
    body1 = comments[0].select_one(selectors["comments"]["text"]).get_text(strip=True)
    assert body1.lower() == "a"

def test_parse_full_media_image(selectors):
    """Test extracting full resolution image from media fixture."""
    fixture = FIXTURES_DIR / "media_q1-webp_134314_clean.html"
    soup = BeautifulSoup(fixture.read_text(encoding="utf-8"), "html.parser")

    img = soup.select_one(selectors["media_detail"]["full_image"])
    assert img is not None, "Full media image element not found"
    src = img.get(selectors["media_detail"]["image_src_attribute"])
    assert "/media/q1-webp.134314/full" in src

def test_sanitization_removes_tokens_and_real_names():
    """Verify that sensitive user info and tokens are sanitized in test fixtures."""
    for fp in FIXTURES_DIR.glob("media_*.html"):
        content = fp.read_text(encoding="utf-8")
        assert "password" not in content.lower(), f"Sensitive keyword leaked in {fp.name}"
        assert "xf_user" not in content, f"Session cookie leaked in {fp.name}"
        assert "[SANITIZED_CSRF_TOKEN]" in content or "data-csrf" not in content
        # Real personal names shouldn't appear in comment user spans
        soup = BeautifulSoup(content, "html.parser")
        for u in soup.select(".message-name, .comment-user"):
            assert u.get_text(strip=True).startswith("Student_")
