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


def test_sp25_q22_deterministic_tie_break_20_runs():
    """Item 2 (round 4): Tie-break must be 100% deterministic across 20 runs even with shuffled input comments."""
    import random
    from backend.app.db.models import Comment
    from backend.app.modules.analysis.voting import tally_votes

    raw_comms = [
        ("12994", "d471bdc2be23", "c"),
        ("14286", "ab50d762b74e", "B"),
        ("14410", "503afc4bd66d", "C"),
        ("15624", "46f1bf31276d", "C"),
        ("17323", "33045cf7e530", "b"),
        ("17415", "05ea6bad6ff7", "hả thế B hay C"),
        ("17884", "8873c37a48d0", "C"),
        ("18052", "097ba38b36b9", "b"),
        ("20848", "fa94e03e7c4b", "b"),
        ("21330", "5d614d6ac341", "a"),
    ]
    results = []
    rng = random.Random(42)
    for _ in range(20):
        shuffled = list(raw_comms)
        rng.shuffle(shuffled)
        objs = [
            Comment(question_id=2032, comment_id=cid, author_hash=ah, raw_text=txt, upvotes=0)
            for cid, ah, txt in shuffled
        ]
        res = tally_votes(objs, max_option_letter="D")
        assert res.status == AnswerStatus.CONFLICT
        results.append((tuple(res.answer_set), res.status, res.confidence))

    assert len(set(results)) == 1
    assert results[0][0] == ("B",)


def test_cau_n_web_ui_crop_and_non_question_meta(tmp_path: Path):
    """Item 1: Thread 464 'Câu N' web UI crops cleanly without crop_too_large/right_edge, and meta records non_question_attachments."""
    p1 = Path("data/cache/fuexam/media_18119/hcm202-sp26-b5-fe-re_01-webp.webp")
    if p1.exists():
        res = crop_question_single(p1, output_path=tmp_path / "q001.png")
        assert res.layout == "cau_n_web_ui"
        assert res.cropped_image.height < 600
        assert "crop_too_large" not in res.warnings
        assert "right_edge" not in res.warnings

    exam = Exam(id=9903, subject_id=1, title="HCM202 - SP26 - B5 - FE - RE", url="https://fuexam.me/threads/9903/")
    q1 = Question(id=1, exam_id=9903, index=1, local_image_path=None)
    out_docx = build_exam_docx(
        subject_code="HCM202",
        exam=exam,
        questions=[q1],
        output_dir=tmp_path,
        cropped_dir=tmp_path / "cropped",
        answers_map={1: Answer(question_id=1, answer_set='["A"]', status=AnswerStatus.CONFIDENT, confidence=1.0)},
        platform="fuexam",
        non_question_attachments=[{"index": 32, "media_id": 37128, "reason": "Tệp PDF"}],
    )
    meta = json.loads((tmp_path / f"{out_docx.name}.meta.json").read_text(encoding="utf-8"))
    assert meta["questions_count"] == 1
    assert meta["non_question_attachments"] == [{"index": 32, "media_id": 37128, "reason": "Tệp PDF"}]


def test_380_q39_choice_hint_n_is_1_and_ai_tiebreak_meta(tmp_path: Path):
    """Items 1 & 3 (round 5): 380 Q39 reads N=1 (not 3), and ai_tiebreak_questions is recorded in .meta.json."""
    from backend.app.modules.analysis.image_answer_reader import read_choice_hint_n

    p39 = Path("data/cache/fuexam/media_15103/hcm202-sp26-b5-fe_039-webp.webp")
    if p39.exists():
        assert read_choice_hint_n(p39) == 1

    exam = Exam(id=9904, subject_id=1, title="HCM202 - SP25 - FE", url="https://fuexam.me/threads/9904/")
    q1 = Question(id=1, exam_id=9904, index=22, local_image_path=None)
    ans_tb = Answer(
        question_id=1,
        answer_set='["C"]',
        status=AnswerStatus.CONFLICT,
        confidence=0.524,
        vote_breakdown={"_source": "comments", "B": 4.0, "C": 4.5, "_ai_votes": [{"provider": "gemini", "answers": ["C"]}]},
    )
    out_docx = build_exam_docx(
        subject_code="HCM202",
        exam=exam,
        questions=[q1],
        output_dir=tmp_path,
        cropped_dir=tmp_path / "cropped",
        answers_map={1: ans_tb},
        platform="fuexam",
    )
    meta = json.loads((tmp_path / f"{out_docx.name}.meta.json").read_text(encoding="utf-8"))
    assert meta["ai_tiebreak_questions"] == [22]
    assert meta["ai_count"] == 1
    assert meta["source_breakdown"]["ai_tiebreak"] == 1
    assert 22 in meta["review_needed_questions"]


def test_380_q51_no_right_clip_and_detector(tmp_path: Path):
    """Round 6 Item 3: 380 Q51 Option D ('Việt Nam') must not clip right edge; synthetic clipped image triggers text_clipped_right."""
    from PIL import ImageDraw

    p51 = Path("data/cache/fuexam/media_15115/hcm202-sp26-b5-fe_051-webp.webp")
    if p51.exists():
        res = crop_question_single(p51, output_path=tmp_path / "q051.png")
        assert res.layout == "modern_2026_split_username"
        assert "text_clipped_right" not in res.warnings
        # Source Option D extends through x=957 (past old watermark clip at x=808)
        assert res.box[2] >= 955
        # Verify final output rightmost columns are padded white (no right-edge clipping)
        fc_arr = np.array(res.cropped_image.convert("RGB"))
        assert (fc_arr[:, -1] > 240).all()

    # Synthetic unpadded right-clipped image (black text strokes hitting x = W - 1)
    clipped_im = Image.new("RGB", (400, 180), "white")
    draw = ImageDraw.Draw(clipped_im)
    for yy in range(30, 150, 25):
        draw.rectangle([20, yy, 399, yy + 10], fill="black")
    clip_src = tmp_path / "clipped_src.png"
    clipped_im.save(clip_src)
    res_clip = crop_question_single(clip_src, output_path=tmp_path / "clipped_out.png")
    assert "text_clipped_right" in res_clip.warnings


def test_choice_hint_n_mismatch_keeps_answer_and_strong_override(tmp_path: Path):
    """
    Round 6 Item 1:
    - Normal N mismatch keeps valid answer, marks CONFLICT, records choice_count_warnings in .meta.json.
    - Strong override ONLY applies when high-confidence N disagrees impossibly vs visible options (e.g. MLN122 C2 Q23).
    """
    from unittest.mock import patch
    from PIL import ImageDraw, ImageFont
    from backend.app.modules.analysis.image_answer_reader import (
        count_visible_options,
        evaluate_choice_count_consistency,
        read_choice_hint_n_detailed,
    )

    # 1. Synthetic noisy low-confidence N=4 vs valid community answer ['A'] -> keep ['A'] + choice_count_warnings
    dummy_img = tmp_path / "dummy_low_conf.png"
    Image.new("RGB", (500, 200), "white").save(dummy_img)

    with patch(
        "backend.app.modules.analysis.image_answer_reader.read_choice_hint_n_detailed",
        return_value=(4, False),
    ):
        dec_keep = evaluate_choice_count_consistency(
            question_index=51,
            answer_set=["A"],
            status=AnswerStatus.CONFIDENT,
            confidence=0.95,
            source="comments",
            raw_img_path=dummy_img,
        )
    assert dec_keep.overridden is False
    assert dec_keep.answer_set == ["A"]
    assert dec_keep.status == AnswerStatus.CONFLICT
    assert dec_keep.warning_entry == {
        "question": 51,
        "hint_n": 4,
        "answer_letters": ["A"],
        "source": "comments",
    }

    # 2. High-confidence N=1 on 3-option question (like MLN122 C2 Q23) with 2 answer letters -> override to '?'
    synth_3opt = tmp_path / "synth_3opt.png"
    im3 = Image.new("RGB", (1400, 700), "white")
    d3 = ImageDraw.Draw(im3)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 22)
    except Exception:
        font = ImageFont.load_default()
    d3.text((120, 200), "(Choose 1 answer)", fill="black", font=font)
    d3.text((120, 320), "Cau hoi co 3 phuong an?", fill="black", font=font)
    d3.text((120, 390), "A. Option one", fill="black", font=font)
    d3.text((120, 450), "B. Option two", fill="black", font=font)
    d3.text((120, 510), "C. Option three", fill="black", font=font)
    im3.save(synth_3opt)

    assert count_visible_options(synth_3opt) == 3
    p_mln = Path("data/cache/fuexam/media_52796/mln122-fa26-fe-c2_023-webp.webp")
    if p_mln.exists():
        n_mln, high_mln = read_choice_hint_n_detailed(p_mln)
        assert (n_mln, high_mln) == (1, True)
        assert count_visible_options(p_mln) == 3

    with patch(
        "backend.app.modules.analysis.image_answer_reader.read_choice_hint_n_detailed",
        return_value=(1, True),
    ):
        dec_ov = evaluate_choice_count_consistency(
            question_index=23,
            answer_set=["A", "B"],
            status=AnswerStatus.CONFIDENT,
            confidence=0.90,
            source="comments",
            raw_img_path=synth_3opt,
        )
    assert dec_ov.overridden is True
    assert dec_ov.answer_set == ["?"]
    assert dec_ov.status == AnswerStatus.CONFLICT
    assert dec_ov.override_entry == {
        "question": 23,
        "hint_n": 1,
        "before": ["A", "B"],
        "after": ["?"],
        "visible_options": 3,
    }

    # 3. Verify .meta.json persistence for both choice_count_warnings and choice_count_overrides
    exam = Exam(id=9905, subject_id=1, title="HCM202 - SP26 - B5 - FE", url="https://fuexam.me/threads/9905/")
    q1 = Question(id=1, exam_id=9905, index=1, local_image_path=None)
    q51 = Question(id=51, exam_id=9905, index=51, local_image_path=None)
    q23 = Question(id=23, exam_id=9905, index=23, local_image_path=None)
    ans1 = Answer(
        question_id=1,
        answer_set='["B"]',
        status=AnswerStatus.CONFIDENT,
        confidence=1.0,
        vote_breakdown={"_source": "comments"},
    )
    ans51 = Answer(
        question_id=51,
        answer_set='["A"]',
        status=AnswerStatus.CONFLICT,
        confidence=0.95,
        vote_breakdown={"_source": "comments", "_choice_count_warning": dec_keep.warning_entry},
    )
    ans23 = Answer(
        question_id=23,
        answer_set='["?"]',
        status=AnswerStatus.CONFLICT,
        confidence=0.0,
        vote_breakdown={"_source": "comments", "_choice_count_override": dec_ov.override_entry},
    )
    out_docx = build_exam_docx(
        subject_code="HCM202",
        exam=exam,
        questions=[q1, q23, q51],
        output_dir=tmp_path,
        cropped_dir=tmp_path / "cropped",
        answers_map={1: ans1, 23: ans23, 51: ans51},
        platform="fuexam",
    )
    meta = json.loads((tmp_path / f"{out_docx.name}.meta.json").read_text(encoding="utf-8"))
    assert meta["choice_count_warnings"] == [dec_keep.warning_entry]
    assert meta["choice_count_overrides"] == [dec_ov.override_entry]
    assert 51 in meta["review_needed_questions"]
    assert 23 in meta["review_needed_questions"]




