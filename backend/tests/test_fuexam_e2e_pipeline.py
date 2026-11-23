"""
backend/tests/test_fuexam_e2e_pipeline.py
End-to-end test cho luồng biên soạn fuexam với dữ liệu giả (mock/synthetic data):
1. Kết quả đầu ra đúng cấu trúc thư mục:
   data/output/FUE/{MÔN}/{MÔN} - FUE - {KỲ} - [B5 -] {LOẠI} [- RE].docx
2. Tệp siêu dữ liệu đi kèm ({filename}.meta.json) được sinh tự động bởi code build_exam_docx:
   - Có updated_at thời gian thực (định dạng ISO)
   - Có đầy đủ các trường thống kê (confident_count, weak_count, conflict_count, v.v.)
3. Không còn bất kỳ hậu tố cảnh báo nào trong tài liệu Word (như "(cần kiểm tra lại)"):
   - Dù câu hỏi ở trạng thái WEAK, CONFLICT, hoặc NO_DATA, dòng đáp án trong Word
     chỉ chứa ký tự đáp án (20pt đỏ đậm), cảnh báo được đưa hoàn toàn vào .meta.json.
"""

import json
from pathlib import Path
from PIL import Image
import pytest
from docx import Document

from backend.app.db.models import Answer, AnswerStatus, Exam, ExamType, Question
from backend.app.modules.export.docx_builder import build_exam_docx


@pytest.fixture
def mock_fuexam_env(tmp_path):
    """Tạo môi trường thư mục tạm và ảnh mẫu cho test end-to-end."""
    img_dir = tmp_path / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    
    # Tạo ảnh mẫu RGB hợp lệ
    sample_img_path = img_dir / "q_sample.png"
    im = Image.new("RGB", (400, 200), color=(255, 255, 255))
    im.save(sample_img_path)

    out_base = tmp_path / "data" / "output" / "FUE"
    out_base.mkdir(parents=True, exist_ok=True)

    return {
        "tmp_path": tmp_path,
        "sample_img": sample_img_path,
        "out_base": out_base,
    }


def test_fuexam_e2e_b5_pipeline(mock_fuexam_env):
    """
    Test E2E luồng đề B5:
    - Đầu ra: data/output/FUE/PRM393/PRM393 - FUE - SU26 - B5 - FE.docx
    - Đi kèm: PRM393 - FUE - SU26 - B5 - FE.docx.meta.json do code sinh ra
    - Không có hậu tố cảnh báo trong Word
    """
    subject_code = "PRM393"
    exam_dir = mock_fuexam_env["out_base"] / subject_code
    exam_dir.mkdir(parents=True, exist_ok=True)

    exam = Exam(
        id=1174,
        title="PRM393 - SU26 - B5 - FE",
        term="SU26",
        exam_type=ExamType.FE,
        platform="fuexam",
        crop_layout="fuexam_2026",
    )

    questions = []
    answers_map = {}
    for idx in range(1, 4):
        q = Question(
            id=idx,
            exam_id=exam.id,
            index=idx,
            local_image_path=str(mock_fuexam_env["sample_img"]),
            cropped_image_path=str(mock_fuexam_env["sample_img"]),
        )
        ans = Answer(
            id=idx,
            question_id=idx,
            answer_set=["B"],
            status=AnswerStatus.CONFIDENT,
            confidence=1.0,
            vote_breakdown={"_source": "image"},
        )
        q.answer = ans
        questions.append(q)
        answers_map[idx] = ans

    docx_path = build_exam_docx(
        subject_code=subject_code,
        exam=exam,
        questions=questions,
        output_dir=exam_dir,
        cropped_dir=mock_fuexam_env["tmp_path"] / "images",
        platform="fuexam",
        add_question_number=False,
        add_divider=True,
        answers_map=answers_map,
    )

    # 1. Kiểm tra đường dẫn và định dạng tên file
    expected_filename = "PRM393 - FUE - SU26 - B5 - FE.docx"
    assert docx_path.name == expected_filename
    assert docx_path.exists()
    assert docx_path.parent == exam_dir
    assert "FUE" in str(docx_path)

    # 2. Kiểm tra sidecar .meta.json sinh tự động bởi code
    meta_path = exam_dir / f"{expected_filename}.meta.json"
    assert meta_path.exists()
    meta_data = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta_data["filename"] == expected_filename
    assert meta_data["subject_code"] == "PRM393"
    assert meta_data["platform"] == "fuexam"
    assert meta_data["questions_count"] == 3
    assert meta_data["confident_count"] == 3
    assert meta_data["weak_count"] == 0
    assert meta_data["image_count"] == 3
    assert "updated_at" in meta_data
    assert len(meta_data["updated_at"]) > 10

    # 3. Kiểm tra nội dung file Word: TUYỆT ĐỐI không có hậu tố cảnh báo
    doc = Document(docx_path)
    full_text = " ".join(p.text for p in doc.paragraphs)
    assert "cần kiểm tra lại" not in full_text
    assert "(cần kiểm tra lại)" not in full_text
    assert "ảnh có thể thiếu" not in full_text


def test_fuexam_e2e_re_pipeline_with_weak_and_conflict_answers(mock_fuexam_env):
    """
    Test E2E luồng đề RE với các câu hỏi có độ tin cậy yếu / tranh chấp:
    - Đầu ra: data/output/FUE/PRM393/PRM393 - FUE - SU26 - FE - RE.docx
    - Đi kèm: PRM393 - FUE - SU26 - FE - RE.docx.meta.json
    - Dù có WEAK hay CONFLICT, trong Word KHÔNG CÓ hậu tố '(cần kiểm tra lại)',
      chỉ có đáp án chuẩn, và các câu nghi vấn được ghi đầy đủ vào review_needed_questions.
    """
    subject_code = "PRM393"
    exam_dir = mock_fuexam_env["out_base"] / subject_code
    exam_dir.mkdir(parents=True, exist_ok=True)

    exam = Exam(
        id=941,
        title="PRM393 - SU26 - FE - RE",
        term="SU26",
        exam_type=ExamType.FE,
        platform="fuexam",
        crop_layout="fuexam_2026",
    )

    questions = []
    answers_map = {}
    
    # Q1: CONFIDENT (B)
    q1 = Question(id=1, exam_id=exam.id, index=1, local_image_path=str(mock_fuexam_env["sample_img"]))
    a1 = Answer(id=1, question_id=1, answer_set=["B"], status=AnswerStatus.CONFIDENT, confidence=1.0, vote_breakdown={"_source": "community"})
    q1.answer = a1
    questions.append(q1)
    answers_map[1] = a1

    # Q2: WEAK (C) - Trước đây bị gắn '(cần kiểm tra lại)'
    q2 = Question(id=2, exam_id=exam.id, index=2, local_image_path=str(mock_fuexam_env["sample_img"]))
    a2 = Answer(id=2, question_id=2, answer_set=["C"], status=AnswerStatus.WEAK, confidence=0.55, vote_breakdown={"_source": "community"})
    q2.answer = a2
    questions.append(q2)
    answers_map[2] = a2

    # Q3: CONFLICT (A) - Trước đây bị gắn '(cần kiểm tra lại)'
    q3 = Question(id=3, exam_id=exam.id, index=3, local_image_path=str(mock_fuexam_env["sample_img"]))
    a3 = Answer(id=3, question_id=3, answer_set=["A"], status=AnswerStatus.CONFLICT, confidence=0.50, vote_breakdown={"_source": "community"})
    q3.answer = a3
    questions.append(q3)
    answers_map[3] = a3

    docx_path = build_exam_docx(
        subject_code=subject_code,
        exam=exam,
        questions=questions,
        output_dir=exam_dir,
        cropped_dir=mock_fuexam_env["tmp_path"] / "images",
        platform="fuexam",
        add_question_number=False,
        add_divider=True,
        answers_map=answers_map,
    )

    # 1. Tên file chuẩn định dạng
    expected_filename = "PRM393 - FUE - SU26 - FE - RE.docx"
    assert docx_path.name == expected_filename
    assert docx_path.exists()

    # 2. Sidecar .meta.json lưu đúng số liệu và danh sách câu cần xem lại
    meta_path = exam_dir / f"{expected_filename}.meta.json"
    assert meta_path.exists()
    meta_data = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta_data["filename"] == expected_filename
    assert meta_data["questions_count"] == 3
    assert meta_data["confident_count"] == 1
    assert meta_data["weak_count"] == 1
    assert meta_data["conflict_count"] == 1
    assert meta_data["review_needed_questions"] == [2, 3]
    assert "updated_at" in meta_data

    # 3. Tài liệu Word: KHÔNG CÒN hậu tố cảnh báo
    doc = Document(docx_path)
    full_text = " ".join(p.text for p in doc.paragraphs)
    assert "cần kiểm tra lại" not in full_text
    assert "(cần kiểm tra lại)" not in full_text
    
    # Đảm bảo các đáp án hiển thị sạch sẽ
    answer_paras = [p for p in doc.paragraphs if any(r.font.size and r.font.size.pt == 20 for r in p.runs)]
    assert len(answer_paras) == 3
    assert answer_paras[0].text == "B"
    assert answer_paras[1].text == "C"
    assert answer_paras[2].text == "A"


def test_fuexam_e2e_mae101_standard_fe(mock_fuexam_env):
    """
    Test E2E luồng đề chuẩn MAE101:
    - Đầu ra: data/output/FUE/MAE101/MAE101 - FUE - FA26 - FE.docx
    - Đi kèm: MAE101 - FUE - FA26 - FE.docx.meta.json
    - Không có hậu tố cảnh báo
    """
    subject_code = "MAE101"
    exam_dir = mock_fuexam_env["out_base"] / subject_code
    exam_dir.mkdir(parents=True, exist_ok=True)

    exam = Exam(
        id=1587,
        title="MAE101 - FA26 - FE",
        term="FA26",
        exam_type=ExamType.FE,
        platform="fuexam",
        crop_layout="fuexam_2026",
    )

    questions = []
    answers_map = {}
    for idx in range(1, 4):
        q = Question(
            id=idx,
            exam_id=exam.id,
            index=idx,
            local_image_path=str(mock_fuexam_env["sample_img"]),
        )
        ans = Answer(
            id=idx,
            question_id=idx,
            answer_set=["A"],
            status=AnswerStatus.CONFIDENT,
            confidence=1.0,
            vote_breakdown={"_source": "image"},
        )
        q.answer = ans
        questions.append(q)
        answers_map[idx] = ans

    docx_path = build_exam_docx(
        subject_code=subject_code,
        exam=exam,
        questions=questions,
        output_dir=exam_dir,
        cropped_dir=mock_fuexam_env["tmp_path"] / "images",
        platform="fuexam",
        add_question_number=False,
        add_divider=True,
        answers_map=answers_map,
    )

    expected_filename = "MAE101 - FUE - FA26 - FE.docx"
    assert docx_path.name == expected_filename
    assert docx_path.exists()

    meta_path = exam_dir / f"{expected_filename}.meta.json"
    assert meta_path.exists()
    meta_data = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta_data["filename"] == expected_filename
    assert meta_data["subject_code"] == "MAE101"
    assert meta_data["platform"] == "fuexam"
    assert meta_data["questions_count"] == 3
    assert meta_data["confident_count"] == 3

    doc = Document(docx_path)
    full_text = " ".join(p.text for p in doc.paragraphs)
    assert "cần kiểm tra lại" not in full_text
