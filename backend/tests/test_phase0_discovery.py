"""
tests/test_phase0_discovery.py - Automated verification tests for Phase 0 deliverables.

Verifies:
1. selectors.yaml validity and structure
2. config.yaml validity and structure
3. Parsing of sample_subject_csd202.html fixture
4. Parsing of sample_thread_fe_csd202.html fixture
5. Parsing of sample_thread_pe_csd202.html fixture
6. Parsing of sample_media_lightbox_q1.html fixture
"""

import re
from pathlib import Path
import yaml
import pytest
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = BASE_DIR / "backend" / "config"
FIXTURES_DIR = BASE_DIR / "data" / "fixtures"


@pytest.fixture
def selectors():
    path = CONFIG_DIR / "selectors.yaml"
    assert path.exists(), "selectors.yaml does not exist"
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data


@pytest.fixture
def app_config():
    path = CONFIG_DIR / "config.yaml"
    assert path.exists(), "config.yaml does not exist"
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data


def test_selectors_yaml_structure(selectors):
    """Verify selectors.yaml contains required root sections."""
    required_sections = ["base_url", "endpoints", "auth", "subjects", "exams", "questions", "comments"]
    for s in required_sections:
        assert s in selectors, f"Missing section '{s}' in selectors.yaml"
    assert selectors["base_url"].startswith("http")


def test_config_yaml_structure(app_config):
    """Verify config.yaml contains required root sections."""
    required_sections = ["exam", "crawl", "analysis", "export"]
    for s in required_sections:
        assert s in app_config, f"Missing section '{s}' in config.yaml"
    assert app_config["exam"]["default_count"] >= 1


def test_parse_subject_threads(selectors):
    """Test extracting exam threads and detecting FE vs PE from subject fixture."""
    fixture_path = FIXTURES_DIR / "sample_subject_csd202.html"
    assert fixture_path.exists(), "Subject fixture missing"

    content = fixture_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(content, "html.parser")

    # Find thread items
    threads = soup.select(selectors["exams"]["item"])
    assert len(threads) >= 5, f"Expected at least 5 threads in CSD202, got {len(threads)}"

    fe_count = 0
    pe_count = 0

    for t in threads:
        # Title link
        title_el = t.select_one(selectors["exams"]["title_link"])
        assert title_el is not None
        title_text = title_el.get_text(strip=True)
        href = title_el.get("href")
        assert "/threads/" in href

        # Badge / label
        badge = t.select_one(selectors["exams"]["prefix_badge"])
        badge_text = badge.get_text(strip=True) if badge else ""

        if selectors["exams"]["fe_label"] in badge_text or "-fe." in href:
            fe_count += 1
        elif selectors["exams"]["pe_label"] in badge_text or "-pe-" in href:
            pe_count += 1

    assert fe_count >= 1, "Must detect at least 1 FE exam"
    assert pe_count >= 1, "Must detect at least 1 PE exam"


def test_parse_fe_questions(selectors):
    """Test extracting all 50 questions and image URLs from FE thread fixture."""
    fixture_path = FIXTURES_DIR / "sample_thread_fe_csd202.html"
    assert fixture_path.exists(), "FE thread fixture missing"

    content = fixture_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(content, "html.parser")

    # Locate attachment items
    questions = soup.select(selectors["questions"]["item"])
    assert len(questions) == 50, f"Expected 50 questions in CSD202 FE, got {len(questions)}"

    # Check question 1
    q1 = questions[0]
    name_el = q1.select_one(selectors["questions"]["file_name"])
    assert name_el is not None
    assert "Q1.webp" in name_el.get_text(strip=True)

    img_el = q1.select_one(selectors["questions"]["image"])
    assert img_el is not None
    img_src = img_el.get("src")
    assert "data.fuoverflow.com/attachments/" in img_src

    # Check media link for comments
    preview_link = q1.select_one(selectors["questions"]["preview_link"])
    assert preview_link is not None
    sidebar_href = preview_link.get(selectors["questions"]["media_link_attribute"])
    assert sidebar_href is not None
    assert "/media/q1-webp" in sidebar_href


def test_parse_pe_attachments(selectors):
    """Test extracting practical exam attachments from PE fixture."""
    fixture_path = FIXTURES_DIR / "sample_thread_pe_csd202.html"
    assert fixture_path.exists(), "PE thread fixture missing"

    content = fixture_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(content, "html.parser")

    files = soup.select(selectors["questions"]["item"])
    assert len(files) >= 1, "Expected at least 1 attachment in PE thread"

    file_names = [f.select_one(selectors["questions"]["file_name"]).get_text(strip=True) for f in files]
    assert any(".zip" in fn for fn in file_names)
    assert any(".pdf" in fn for fn in file_names)


def test_parse_login_requirement(selectors):
    """Test login detection from media fixture."""
    fixture_path = FIXTURES_DIR / "sample_media_lightbox_q1.html"
    assert fixture_path.exists(), "Media fixture missing"

    content = fixture_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(content, "html.parser")

    # Check logged out state
    is_logged_in = soup.select_one(selectors["auth"]["logged_in_selector"])
    assert is_logged_in is None, "Expected logged_in_selector to be None on logged-out fixture"

    # Check presence of Google login button
    google_btn = soup.select_one(selectors["auth"]["google_button"])
    assert google_btn is not None
    assert "/register/connected-accounts/google/" in google_btn.get("href")

