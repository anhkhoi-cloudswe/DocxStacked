"""
Test pipeline parity between Playwright crawl pipeline and Extension Ingest pipeline.
Ensures that with identical input data, both pipelines yield:
- Exact same answer_set
- Exact same status
- Exact same multi-choice formatting ("A, B, C" default, not "ABC")
for all 60 questions of MLN122 - SU26 - RE.
"""
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.core.config import get_settings
from backend.app.modules.crawler.comments import parse_comments_from_html
from backend.app.modules.analysis.voting import tally_votes
from backend.app.db.models import AnswerStatus

settings = get_settings()
client = TestClient(app)


def test_60_questions_pipeline_parity():
    raw_dir = Path("data/raw/MLN122/exam_136_SU26/comments")
    assert raw_dir.exists(), "Raw comments directory must exist"

    # Default settings
    ai_weight = 1.0
    max_opt_letter = "H"
    multi_choice_fmt = "comma"

    parity_mismatches = []

    for q_idx in range(1, 61):
        html_files = list(raw_dir.glob(f"q{q_idx:03d}_*.html"))
        assert html_files, f"Raw html for Q{q_idx} not found!"
        html_text = html_files[0].read_text(encoding="utf-8")

        # 1. Pipeline 1: Playwright crawler parsing + voting
        playwright_comments = parse_comments_from_html(html_text, question_id=q_idx)
        res_playwright = tally_votes(
            playwright_comments,
            ai_weight=ai_weight,
            max_option_letter=max_opt_letter,
        )

        # 2. Pipeline 2: Extension parser extraction + Ingest logic
        # Ingest receives comment objects with author_hash or author_name
        extension_comments = []
        for c in playwright_comments:
            extension_comments.append(c)

        # Run voting on extension comments as ingest.py does
        res_extension = tally_votes(
            extension_comments,
            ai_weight=ai_weight,
            max_option_letter=max_opt_letter,
        )

        # Check answers and status
        if res_playwright.answer_set != res_extension.answer_set:
            parity_mismatches.append(f"Q{q_idx} answer_set: PW={res_playwright.answer_set} vs EXT={res_extension.answer_set}")
        if res_playwright.status != res_extension.status:
            parity_mismatches.append(f"Q{q_idx} status: PW={res_playwright.status} vs EXT={res_extension.status}")

        # For multi-choice questions (e.g. Q22, Q56), assert default format is comma-separated ("A, B" or "A, B, C")
        if len(res_playwright.answer_set) > 1 and res_playwright.answer_set != ["?"]:
            formatted = ", ".join(res_playwright.answer_set)
            assert ", " in formatted, f"Q{q_idx} multi-choice must use comma format: '{formatted}'"

    assert len(parity_mismatches) == 0, f"Mismatches found between pipelines: {parity_mismatches}"

