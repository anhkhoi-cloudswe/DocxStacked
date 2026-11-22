"""
Tests for MLN122 4-error fixes:
1. Vietnamese multi-choice hint parsing & comment mode inference (Q22 -> A, B, C; Q27 -> A, B, C).
2. Multi-choice letter-only formatting (comma "A, B, C" & joined "ABC", no keywords).
3. Keyword validation & prevention of wrong/translated keywords (reject English on VI exams, reject placeholders).
4. Missing options handling in source image (flag 'missing_options', note in Word, no AI call, no placeholder strings).
"""

from pathlib import Path
import pytest
from docx import Document

from backend.app.db.models import Answer, AnswerStatus, Comment, Exam, Question
from backend.app.modules.analysis.parser import (
    infer_multi_choice_n_from_comments,
    parse_choice_hint,
    parse_comment_text,
)
from backend.app.modules.analysis.voting import tally_votes
from backend.app.modules.export.docx_builder import (
    _render_question_to_doc,
    is_valid_keyword,
)
from backend.app.modules.export.image_cropper import crop_question_single


# ---------------------------------------------------------------------------
# 1. Vietnamese Multi-choice Hint Parsing & Comment Mode Inference
# ---------------------------------------------------------------------------

def test_vietnamese_choice_hint_parsing():
    """Verify parsing of Vietnamese and English choice hints."""
    cases = [
        ("(chọn nhiều đáp án)", (True, None)),
        ("(chọn các đáp án đúng)", (True, None)),
        ("(lựa chọn ba đáp án)", (True, 3)),
        ("(chọn 3 phương án đúng)", (True, 3)),
        ("(chọn hai đáp án)", (True, 2)),
        ("(chọn 2 đáp án)", (True, 2)),
        ("(chọn bốn phương án đúng)", (True, 4)),
        ("(chọn năm đáp án)", (True, 5)),
        ("(Choose 1 answer)", (False, 1)),
        ("(Choose 2 answers)", (True, 2)),
        ("(Choose 3 answers)", (True, 3)),
        ("(Choose multiple answers)", (True, None)),
        ("(Select 2 options)", (True, 2)),
        ("(Select multiple options)", (True, None)),
        ("Câu hỏi bình thường không có gợi ý", (False, None)),
    ]
    for text, expected in cases:
        assert parse_choice_hint(text) == expected, f"Failed on: {text}"


def test_comment_mode_inference():
    """Verify inferring N from comment lengths mode."""
    # Concatenated letters
    assert infer_multi_choice_n_from_comments(["ABC", "abc", "ABC"]) == 3
    assert infer_multi_choice_n_from_comments(["ACD", "acd", "ACD"]) == 3
    # Separated letters
    assert infer_multi_choice_n_from_comments(["A, B, C", "a, b, c", "A, B, C"]) == 3
    # Single-letter comments do not infer N
    assert infer_multi_choice_n_from_comments(["A", "B", "A", "A"]) is None


def test_q22_and_q27_produce_abc():
    """
    Requirement 1:
    - Q27 with comments ['ABC', 'abc', 'ABC'] and hint '(chọn nhiều đáp án)' must produce A, B, C.
    - Q22 with comments ['AC', 'AB', 'AB', 'AB', 'abd', 'AB'] and hint '(lựa chọn ba đáp án)' / '(chọn 3 phương án đúng)' must produce A, B, C.
    """
    # Q27: Mode = 3 inferred from comments
    comms_27 = [
        Comment(id=1, author_hash="u1", raw_text="ABC"),
        Comment(id=2, author_hash="u2", raw_text="abc"),
        Comment(id=3, author_hash="u3", raw_text="ABC"),
    ]
    res_27 = tally_votes(comms_27, choice_hint_text="(chọn nhiều đáp án)")
    assert res_27.answer_set == ["A", "B", "C"]
    assert res_27.status == AnswerStatus.CONFIDENT

    # Q22: Hint specifies 3 answers
    comms_22 = [
        Comment(id=1, author_hash="u1", raw_text="AC"),
        Comment(id=2, author_hash="u2", raw_text="AB"),
        Comment(id=3, author_hash="u3", raw_text="AB"),
        Comment(id=4, author_hash="u4", raw_text="AB"),
        Comment(id=5, author_hash="u5", raw_text="abd"),
        Comment(id=6, author_hash="u6", raw_text="AB"),
    ]
    res_22_word = tally_votes(comms_22, choice_hint_text="(lựa chọn ba đáp án)")
    assert res_22_word.answer_set == ["A", "B", "C"]

    res_22_digit = tally_votes(comms_22, choice_hint_text="(chọn 3 phương án đúng)")
    assert res_22_digit.answer_set == ["A", "B", "C"]


# ---------------------------------------------------------------------------
# 2. Multi-choice Formatting in Word (Only Letters, No Keywords)
# ---------------------------------------------------------------------------

def test_multi_choice_only_letters_no_keywords():
    """
    Requirement 2:
    - Multi-choice questions must NEVER display keywords, only letters.
    - Default format is 'A, B, C'.
    - Configurable 'ABC' joined format is supported.
    """
    doc = Document()
    q = Question(id=101, index=1, local_image_path=None, crop_warnings=[])
    ans = Answer(
        question_id=101,
        answer_set='["A", "B", "C"]',
        status=AnswerStatus.CONFIDENT,
        confidence=1.0,
        vote_breakdown={"_options": {"A": "Keyword A", "B": "Keyword B", "C": "Keyword C"}},
    )

    # 1. Default comma format: "A, B, C"
    ans_rendered_comma = _render_question_to_doc(
        doc=doc,
        q=q,
        cropped_dir=Path("tmp"),
        answer_format="letter_keyword",
        multi_choice_format="comma",
        answers_map={101: ans},
        subject_code="MLN122",
    )
    assert ans_rendered_comma == "A, B, C"
    assert "Keyword" not in ans_rendered_comma

    # 2. Joined format: "ABC"
    ans_rendered_joined = _render_question_to_doc(
        doc=doc,
        q=q,
        cropped_dir=Path("tmp"),
        answer_format="letter_keyword",
        multi_choice_format="joined",
        answers_map={101: ans},
        subject_code="MLN122",
    )
    assert ans_rendered_joined == "ABC"
    assert "Keyword" not in ans_rendered_joined


# ---------------------------------------------------------------------------
# 3. Keyword Validation & Language Match
# ---------------------------------------------------------------------------

def test_keyword_validation():
    """
    Requirement 3:
    - Reject placeholder strings like 'Không rõ từ hình ảnh', 'unknown', 'unclear'.
    - Reject English keywords when the exam is Vietnamese.
    - Accept valid Vietnamese keywords.
    """
    # Placeholders must be rejected
    assert not is_valid_keyword("Không rõ từ hình ảnh", is_vietnamese_exam=True)
    assert not is_valid_keyword("không rõ", is_vietnamese_exam=True)
    assert not is_valid_keyword("unknown", is_vietnamese_exam=False)
    assert not is_valid_keyword("unclear", is_vietnamese_exam=False)

    # English translated keywords rejected on Vietnamese exam
    assert not is_valid_keyword("capitalist production costs blurred c and v", is_vietnamese_exam=True)
    assert not is_valid_keyword("capitalist costs smaller than selling price", is_vietnamese_exam=True)
    assert not is_valid_keyword("formation of surplus value and costs", is_vietnamese_exam=True)
    assert not is_valid_keyword("Primitive accumulation", is_vietnamese_exam=True)
    assert not is_valid_keyword("Primitive accumulation", is_vietnamese_exam=True, option_image_text="A. Tích luỹ nguyên thuỷ của tư bản")

    # Match with option text in image
    assert is_valid_keyword("Tích luỹ nguyên thuỷ", is_vietnamese_exam=True, option_image_text="A. Tích luỹ nguyên thuỷ của chủ nghĩa tư bản")
    assert is_valid_keyword("Tích luỹ nguyên thuỷ", is_vietnamese_exam=True)
    assert is_valid_keyword("CNXH", is_vietnamese_exam=True, option_image_text="A. Quá độ lên CNXH bỏ qua TBCN")
    assert is_valid_keyword("GDP", is_vietnamese_exam=True, option_image_text="B. Tăng trưởng chỉ số GDP hàng năm")

    # Valid Vietnamese keywords accepted
    assert is_valid_keyword("Đại hội đảng XII", is_vietnamese_exam=True)
    assert is_valid_keyword("đầu thập niên 50 thế kỷ XX", is_vietnamese_exam=True)
    assert is_valid_keyword("sản phẩm của lao động", is_vietnamese_exam=True)


def test_single_choice_rejects_unmatched_or_translated_keyword():
    """Single-choice question on Vietnamese exam falls back to letter when keyword is English."""
    doc = Document()
    q = Question(id=102, index=2, local_image_path=None, crop_warnings=[])
    ans = Answer(
        question_id=102,
        answer_set='["A"]',
        status=AnswerStatus.CONFIDENT,
        confidence=1.0,
        vote_breakdown={"_options": {"A": "capitalist production costs blurred c and v"}},
    )

    rendered = _render_question_to_doc(
        doc=doc,
        q=q,
        cropped_dir=Path("tmp"),
        answer_format="letter_keyword",
        answers_map={102: ans},
        subject_code="MLN122",
    )
    # English keyword rejected on MLN122 -> outputs only letter "A"
    assert rendered == "A"
    assert "capitalist" not in rendered


# ---------------------------------------------------------------------------
# 4. Missing Options in Source Image
# ---------------------------------------------------------------------------

def test_missing_options_crops_and_word_output():
    """
    Requirement 4:
    - Flag 'missing_options' on images with height < 80px or few lines.
    - Word output includes note '(ảnh nguồn thiếu phương án)'.
    - Placeholders like 'Không rõ từ hình ảnh' must NEVER leak into Word.
    """
    doc = Document()
    q = Question(
        id=103,
        index=6,
        local_image_path=None,
        crop_warnings=["few_lines", "missing_options"],
    )
    ans = Answer(
        question_id=103,
        answer_set='["A"]',
        status=AnswerStatus.WEAK,
        confidence=1.0,
        vote_breakdown={"_options": {"A": "Không rõ từ hình ảnh"}},
    )

    rendered = _render_question_to_doc(
        doc=doc,
        q=q,
        cropped_dir=Path("tmp"),
        answer_format="letter_keyword",
        answers_map={103: ans},
        subject_code="MLN122",
    )

    # Must contain majority letter and "(ảnh nguồn thiếu phương án)"
    assert "A (ảnh nguồn thiếu phương án)" in rendered
    # Must NEVER contain placeholder
    assert "Không rõ từ hình ảnh" not in rendered

    # Check paragraph text in document (per requirement: BỎ hậu tố "(cần kiểm tra lại)" from docx)
    full_text = " ".join(p.text for p in doc.paragraphs)
    assert "A (ảnh nguồn thiếu phương án)" in full_text
    assert "(cần kiểm tra lại)" not in full_text
    assert "Không rõ từ hình ảnh" not in full_text
