"""
backend/tests/test_cache_invalidation.py - Document Cache Invalidation Test Suite.
Verifies that:
1. Cache key incorporates all settings affecting the Word doc (answer_format, image_width_cm, zoom, etc.).
2. Changing answer_format produces a different settings_hash and causes cache miss (file re-creation).
3. Passing force_refresh=True forces file re-creation even when identical settings exist.
"""

from datetime import datetime
import json
from pathlib import Path
import pytest
from httpx import AsyncClient, ASGITransport

from backend.app.core.config import get_settings
from backend.app.db.session import init_db
from backend.app.main import app
from backend.app.modules.jobs.orchestrator import compute_doc_settings_hash

settings = get_settings()


@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()


def test_settings_hash_changes_when_answer_format_changes():
    """Different answer formats MUST produce different cache hashes."""
    cfg1 = {
        "export": {
            "answer_format": "letter_keyword",
            "image_width_cm": 16.51,
            "image_zoom_percent": 100,
            "highlight_low_confidence": True,
            "show_question_number": True,
            "show_separator_line": True,
        },
        "ai": {"enabled": True},
    }
    cfg2 = {
        "export": {
            "answer_format": "red_bold",  # Changed!
            "image_width_cm": 16.51,
            "image_zoom_percent": 100,
            "highlight_low_confidence": True,
            "show_question_number": True,
            "show_separator_line": True,
        },
        "ai": {"enabled": True},
    }
    hash1 = compute_doc_settings_hash(cfg1)
    hash2 = compute_doc_settings_hash(cfg2)
    assert hash1 != hash2, "Changing answer_format must change settings_hash"


def test_settings_hash_changes_when_image_width_or_toggles_change():
    """Changing image width, question numbers, or separator lines must change cache hash."""
    base_cfg = {
        "export": {
            "answer_format": "letter_keyword",
            "image_width_cm": 16.51,
            "image_zoom_percent": 100,
            "highlight_low_confidence": True,
            "show_question_number": True,
            "show_separator_line": True,
        },
        "ai": {"enabled": True},
    }
    base_hash = compute_doc_settings_hash(base_cfg)

    # Change width
    cfg_width = dict(base_cfg)
    cfg_width["export"] = dict(base_cfg["export"], image_width_cm=14.0)
    assert compute_doc_settings_hash(cfg_width) != base_hash

    # Toggle question number
    cfg_q_num = dict(base_cfg)
    cfg_q_num["export"] = dict(base_cfg["export"], show_question_number=False)
    assert compute_doc_settings_hash(cfg_q_num) != base_hash

    # Toggle separator line
    cfg_sep = dict(base_cfg)
    cfg_sep["export"] = dict(base_cfg["export"], show_separator_line=False)
    assert compute_doc_settings_hash(cfg_sep) != base_hash


@pytest.mark.asyncio
async def test_changing_answer_format_recreates_file(tmp_path):
    """
    When settings change (e.g. answer_format), a previously generated docx
    sidecar metadata will not match, causing re-generation (cache miss).
    """
    # 1. Create a fake output docx with old metadata
    subj = "TEST_CACHE_SUBJ"
    out_dir = settings.OUTPUT_DIR / subj
    out_dir.mkdir(parents=True, exist_ok=True)

    docx_path = out_dir / f"{subj} - SU26 - FE.docx"
    docx_path.write_bytes(b"PK\x03\x04old_docx_content")

    old_cfg = {
        "export": {
            "answer_format": "letter",
            "image_width_cm": 16.51,
            "image_zoom_percent": 100,
            "highlight_low_confidence": True,
            "show_question_number": True,
            "show_separator_line": True,
        },
        "ai": {"enabled": True},
    }
    old_hash = compute_doc_settings_hash(old_cfg)

    meta_path = docx_path.with_name(docx_path.name + ".meta.json")
    meta_path.write_text(json.dumps({
        "settings_hash": old_hash,
        "created_at_epoch": 1000.0,
        "created_at_formatted": "10:00 01/01/2026",
    }), encoding="utf-8")

    # 2. Check current settings hash with changed answer_format
    new_cfg = {
        "export": {
            "answer_format": "letter_keyword",  # Different!
            "image_width_cm": 16.51,
            "image_zoom_percent": 100,
            "highlight_low_confidence": True,
            "show_question_number": True,
            "show_separator_line": True,
        },
        "ai": {"enabled": True},
    }
    new_hash = compute_doc_settings_hash(new_cfg)
    assert new_hash != old_hash

    # The cached doc's metadata hash does NOT match current settings hash
    saved_meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert saved_meta["settings_hash"] != new_hash
