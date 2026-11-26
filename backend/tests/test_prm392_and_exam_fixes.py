import pytest
from pathlib import Path
from backend.app.db.models import AnswerStatus, Comment, Question, Exam
from backend.app.modules.analysis.voting import tally_votes
from backend.app.modules.analysis.parser import parse_comment_text
from backend.app.modules.export.image_cropper import crop_question_single, CROP_ALGORITHM_VERSION
from backend.app.modules.export.docx_builder import _render_question_to_doc
from backend.app.db.models import Answer
import docx

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "crop"


def test_5_option_question_parsing_and_tally():
    """
    Requirement 3:
    - Comments voting for 'E' / 'e' must be tallied and not stripped.
    - max_option_letter allows up to E.
    - Multi-choice unanimous agreement does not flip to CONFLICT.
    """
    # 1. Verify parser extracts 'E' when max_option_letter is E
    parsed_single = parse_comment_text("E", max_option_letter="E")
    assert parsed_single.answers == ["E"]

    parsed_multi = parse_comment_text("A, D, E", max_option_letter="E", is_multi_choice=True)
    assert parsed_multi.answers == ["A", "D", "E"]

    # 2. Tally votes on a 5-option question (Q4 style: 10 students vote A, B, C; negative weights present)
    comments = [
        Comment(author_hash=f"auth_{i}", raw_text="A, B, C", upvotes=5 if i < 8 else -10)
        for i in range(10)
    ]
    res = tally_votes(
        comments,
        ai_votes=[{"provider": "gemini", "answers": ["A", "B", "C"], "confidence": 0.95}],
        max_option_letter="E",
    )
    assert res.status == AnswerStatus.CONFIDENT, f"Expected CONFIDENT, got {res.status}"
    assert res.answer_set == ["A", "B", "C"]
    assert "E" not in res.answer_set

    # 3. Tally votes for a question where students vote for E (Q43 style)
    comments_e = [
        Comment(author_hash=f"voter_{i}", raw_text="E", upvotes=3)
        for i in range(8)
    ]
    res_e = tally_votes(
        comments_e,
        max_option_letter="E",
    )
    assert res_e.status == AnswerStatus.CONFIDENT
    assert res_e.answer_set == ["E"]


def test_flag_separation_vote_vs_image_in_docx(tmp_path: Path):
    """
    Requirement 2:
    - Vote flags (WEAK / CONFLICT / NO_DATA) produce ' (cần kiểm tra lại)'.
    - Image flags produce '(ảnh có thể thiếu)'.
    - Unanimous / confident question with clean image receives NO flag.
    """
    doc = docx.Document()
    dummy_img = FIXTURES_DIR / "2024_q01_short.webp"
    # Create dummy crop in tmp_path
    crop_dir = tmp_path / "crops"
    crop_dir.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copy(dummy_img, crop_dir / "q002.png")
    shutil.copy(dummy_img, crop_dir / "q003.png")
    shutil.copy(dummy_img, crop_dir / "q004.png")

    # Case A: Unanimous / CONFIDENT with clean image (Q2 style)
    q_clean = Question(
        id=2,
        index=2,
        local_image_path=str(dummy_img),
        crop_warnings=[],
    )
    ans_clean = Answer(
        question_id=2,
        answer_set=["A"],
        status=AnswerStatus.CONFIDENT,
        confidence=1.0,
        valid_comments_count=16,
        vote_breakdown={"A": 16.0},
    )
    _render_question_to_doc(
        doc=doc,
        q=q_clean,
        cropped_dir=crop_dir,
        highlight_check_needed=True,
        answers_map={2: ans_clean},
    )
    p_ans = doc.paragraphs[-2]  # before divider
    assert "A" in p_ans.text
    assert "cần kiểm tra lại" not in p_ans.text
    assert "ảnh có thể thiếu" not in p_ans.text

    # Case B: CONFIDENT vote, but source image was clipped at screenshot boundary
    q_clipped = Question(
        id=3,
        index=3,
        local_image_path=str(dummy_img),
        crop_warnings=["source_clipped_content"],
    )
    ans_clipped = Answer(
        question_id=3,
        answer_set=["B", "C"],
        status=AnswerStatus.CONFIDENT,
        confidence=0.96,
        valid_comments_count=19,
        vote_breakdown={"B": 19.0, "C": 19.0},
    )
    _render_question_to_doc(
        doc=doc,
        q=q_clipped,
        cropped_dir=crop_dir,
        highlight_check_needed=True,
        answers_map={3: ans_clipped},
    )
    p_ans_clipped = doc.paragraphs[-2]
    assert "B, C" in p_ans_clipped.text
    assert "(ảnh có thể thiếu)" not in p_ans_clipped.text
    assert "(" not in p_ans_clipped.text
    assert "cần kiểm tra lại" not in p_ans_clipped.text

    # Case C: WEAK / CONFLICT vote with clean image
    q_weak = Question(
        id=4,
        index=4,
        local_image_path=str(dummy_img),
        crop_warnings=[],
    )
    ans_weak = Answer(
        question_id=4,
        answer_set=["D"],
        status=AnswerStatus.CONFLICT,
        confidence=0.5,
        valid_comments_count=4,
        vote_breakdown={"D": 4.0},
    )
    _render_question_to_doc(
        doc=doc,
        q=q_weak,
        cropped_dir=crop_dir,
        highlight_check_needed=True,
        answers_map={4: ans_weak},
    )
    p_ans_weak = doc.paragraphs[-2]
    assert "D" in p_ans_weak.text
    assert "(cần kiểm tra lại)" not in p_ans_weak.text
    assert "ảnh có thể thiếu" not in p_ans_weak.text


def test_crop_algorithm_version_and_red_bar_margin():
    """
    Requirement 1:
    - Cropper version bumped.
    - Fixture with red_bar at x ~ 809 has 0 source_clipped warnings.
    """
    assert CROP_ALGORITHM_VERSION >= "3.1.0"
    q9_fixture = FIXTURES_DIR / "2024_ite302c_fa24_re_q09.webp"
    res = crop_question_single(q9_fixture)
    assert res.success
    assert "source_clipped" not in res.warnings
