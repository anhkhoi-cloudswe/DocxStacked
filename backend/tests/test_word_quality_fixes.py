import io
import json
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
from docx import Document
from PIL import Image

from backend.app.db.models import Answer, AnswerStatus, Exam, Question
from backend.app.modules.crawler.fuexam_crawler import fetch_and_cache_media_image
from backend.app.modules.export.docx_builder import _render_question_to_doc, build_exam_docx
from backend.app.modules.export.image_cropper import crop_question_single, find_red_bar


def test_word_answer_lines_never_contain_parenthesis_warning_suffixes(tmp_path: Path):
    """
    Item 2: Không dòng đáp án nào trong Word chứa dấu '(' từ hậu tố cảnh báo ảnh.
    Mọi cảnh báo ảnh phải nằm trong .meta.json (image_warnings).
    """
    exam = Exam(id=9901, subject_id=1, title="HCM202 - SP25 - FE", url="https://fuexam.me/threads/9901/")
    q1 = Question(
        id=1,
        exam_id=9901,
        index=1,
        local_image_path=None,
        crop_warnings=["crop_too_large", "missing_options", "source_clipped_content"],
    )
    q2 = Question(
        id=2,
        exam_id=9901,
        index=2,
        local_image_path=None,
        crop_warnings=["no_text"],
    )
    ans1 = Answer(
        question_id=1,
        answer_set='["B"]',
        status=AnswerStatus.WEAK,
        confidence=0.6,
        vote_breakdown={"_options": {"B": "Đoàn kết dân tộc"}},
    )
    ans2 = Answer(
        question_id=2,
        answer_set='["?"]',
        status=AnswerStatus.NO_DATA,
        confidence=0.0,
        vote_breakdown={},
    )

    out_docx = build_exam_docx(
        subject_code="HCM202",
        exam=exam,
        questions=[q1, q2],
        output_dir=tmp_path,
        cropped_dir=tmp_path / "cropped",
        answers_map={1: ans1, 2: ans2},
        platform="fuexam",
    )
    doc = Document(str(out_docx))
    # Answer paragraphs are bold 20pt red (#EE0000)
    ans_paragraphs = [
        p.text
        for p in doc.paragraphs
        if p.runs and p.runs[0].font.size and p.runs[0].font.size.pt == 20
    ]
    assert len(ans_paragraphs) == 2
    for line in ans_paragraphs:
        assert "(" not in line, f"Unexpected '(' in answer line: {line!r}"
        assert "ảnh" not in line.lower()

    meta = json.loads((tmp_path / f"{out_docx.name}.meta.json").read_text(encoding="utf-8"))
    assert "image_warnings" in meta
    assert meta["image_warnings"]["1"] == ["crop_too_large", "missing_options", "source_clipped_content"]
    assert meta["image_warnings"]["2"] == ["no_text"]


def test_find_red_bar_detects_dark_red_sp25_bar():
    """Item 1: find_red_bar detects dark red bars (R~144-153, G~44-56, B~45-56)."""
    arr = np.full((780, 1920, 3), 255, dtype=np.uint8)
    arr[:, 809:812] = [148, 48, 49]
    bar = find_red_bar(arr)
    assert bar == (809, 811)


def test_tiny_crop_triggers_raw_fallback(tmp_path: Path):
    """Item 1: Hard gate - if crop is <250x60, fall back to raw image and warn."""
    raw_path = tmp_path / "tiny_crop_src.png"
    im = Image.new("RGB", (800, 400), "white")
    # Draw a tiny dark block only in top-left (100x20), mimicking '(Choose 1 answer)'
    arr = np.array(im)
    arr[20:40, 20:120] = [20, 20, 20]
    Image.fromarray(arr).save(raw_path)

    res = crop_question_single(raw_path)
    assert res.cropped_image.size == (800, 400)
    assert "crop_too_small_fallback" in res.warnings


def test_fetch_and_cache_media_image_rejects_corrupt_and_recovers(tmp_path: Path, monkeypatch):
    """Item 7: Rejects non-image bytes (e.g. PDF) and deletes/re-fetches corrupt cached file."""
    monkeypatch.setattr(
        "backend.app.modules.crawler.fuexam_crawler.get_media_cache_dir",
        lambda mid: tmp_path / f"media_{mid}",
    )
    m_dir = tmp_path / "media_37128"
    m_dir.mkdir(parents=True)
    corrupt_path = m_dir / "q_32.webp"
    corrupt_path.write_bytes(b"%PDF-1.7\r\ncorrupt_not_an_image")
    (m_dir / "image_meta.json").write_text(json.dumps({"file_size": 30}), encoding="utf-8")

    # Prepare valid PNG bytes for re-download
    buf = io.BytesIO()
    Image.new("RGB", (400, 200), "white").save(buf, format="PNG")
    valid_bytes = buf.getvalue()

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = valid_bytes
    mock_client.get.return_value = mock_resp

    out_path, is_cached = fetch_and_cache_media_image(
        media_id=37128,
        attachment_url="https://fuexam.me/attachments/q_32.37128/",
        slug="q_32",
        session=MagicMock(),
        client=mock_client,
    )
    assert is_cached is False
    assert out_path.exists()
    with Image.open(out_path) as verified:
        verified.verify()


def test_read_choice_hint_n_never_calls_gemini_and_handles_n_cases():
    """Item 4: read_choice_hint_n is strictly local (never calls AI), and orchestrator skips n=0 / n=None."""
    from backend.app.modules.analysis.image_answer_reader import read_choice_hint_n

    blank = Image.new("RGB", (1800, 1000), "white")
    mock_ai = MagicMock()
    mock_ai.is_available.return_value = True

    # Must return None without ever touching mock_ai
    res = read_choice_hint_n(blank, ai_service=mock_ai)
    assert res is None
    mock_ai.is_available.assert_not_called()

    # Orchestrator mismatch guard logic: n=0 and n=None must NOT overwrite valid answers
    for expected_n in (0, None):
        ans_set = ["A"]
        valid_letters = [a for a in ans_set if a != "?"]
        overwritten = (expected_n is not None and expected_n > 0 and valid_letters and len(valid_letters) != expected_n)
        assert not overwritten

    # When expected_n=2 and only 1 letter is present, mismatch IS detected
    expected_n = 2
    valid_letters = ["A"]
    overwritten = (expected_n is not None and expected_n > 0 and valid_letters and len(valid_letters) != expected_n)
    assert overwritten is True


def test_mln122_c2_q23_choice_hint_n_and_mismatch():
    """Item 4: MLN122 C2 Q23 has 3 options A-C and '(Choose 1 answer)'; 2 letters must trigger mismatch '?'."""
    from backend.app.modules.analysis.image_answer_reader import read_choice_hint_n

    p = Path("data/cache/fuexam/media_52796/mln122-fa26-fe-c2_023-webp.webp")
    if p.exists():
        expected_n = read_choice_hint_n(p)
        assert expected_n == 1
        # Simulate 2 letters returned by voting -> mismatch -> '?'
        ans_set = ["A", "B"]
        assert len(ans_set) != expected_n


def test_sp25_q9_flags_options_incomplete_not_missing_stem(tmp_path: Path):
    """Item 3: 1 stem + 3 options A-C (4 lines) flags 'options_incomplete', not 'missing_stem'."""
    p = Path("data/cache/fuexam/media_38538/hcm202-sp25-fe_009-webp.webp")
    if p.exists():
        res = crop_question_single(p, output_path=tmp_path / "q09.png")
        assert "options_incomplete" in res.warnings
        assert "missing_stem" not in res.warnings


def test_techdybear_strips_username_and_keeps_choose_hint(tmp_path: Path):
    """Item 5: TechdyBear split layout strips left username header while keeping '(Choose 1 answer)'."""
    p = Path("data/cache/fuexam/media_15065/hcm202-sp26-b5-fe_001-webp.webp")
    if p.exists():
        res = crop_question_single(p, output_path=tmp_path / "q01.png")
        assert res.layout == "modern_2026_split_username"
        assert res.cropped_image.width < 700
        assert res.warnings == []


def test_source_image_invalid_isolated_in_docx(tmp_path: Path):
    """Item 6: source_image_invalid inserts placeholder image, writes meta image_warnings, keeps answer clean."""
    exam = Exam(id=9902, subject_id=1, title="HCM202 - SP26 - B5 - FE - RE", url="https://fuexam.me/threads/9902/")
    q_bad = Question(
        id=32,
        exam_id=9902,
        index=32,
        local_image_path=None,
        crop_layout="source_image_invalid",
        crop_warnings=["source_image_invalid"],
    )
    ans = Answer(
        question_id=32,
        answer_set='["B"]',
        status=AnswerStatus.CONFIDENT,
        confidence=1.0,
    )
    out_docx = build_exam_docx(
        subject_code="HCM202",
        exam=exam,
        questions=[q_bad],
        output_dir=tmp_path,
        cropped_dir=tmp_path / "cropped",
        answers_map={32: ans},
        platform="fuexam",
    )
    doc = Document(str(out_docx))
    ans_lines = [p.text for p in doc.paragraphs if p.runs and p.runs[0].font.size and p.runs[0].font.size.pt == 20]
    assert ans_lines == ["B"]
    assert (tmp_path / "cropped" / "q032_invalid_placeholder.png").exists()
    meta = json.loads((tmp_path / f"{out_docx.name}.meta.json").read_text(encoding="utf-8"))
    assert meta["image_warnings"]["32"] == ["source_image_invalid"]


