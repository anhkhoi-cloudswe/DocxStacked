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


def test_fuexam_e2e_same_subject_different_suffixes_c1_c2(mock_fuexam_env):
    """
    Test E2E cho 2 thread cùng môn/kỳ/loại khác hậu tố (C1, C2):
    - Thread 1473: MLN122 - FA26 - FE - C1
    - Thread 1474: MLN122 - FA26 - FE - C2
    Yêu cầu:
    1. Ra 2 file Word đúng tên riêng biệt, không bị ghi đè:
       - MLN122 - FUE - FA26 - FE - C1.docx
       - MLN122 - FUE - FA26 - FE - C2.docx
    2. Mỗi file có .meta.json riêng, lưu đúng thread_id và source_url.
    3. Thỏa mãn công thức confident + weak + conflict + ai + no_data = total_questions.
    4. Mọi câu hỏi '?' (no_data) phải nằm trong review_needed_questions.
    """
    subject_code = "MLN122"
    exam_dir = mock_fuexam_env["out_base"] / subject_code
    exam_dir.mkdir(parents=True, exist_ok=True)

    # 1. Thread 1473 (C1)
    exam_c1 = Exam(
        id=1473,
        title="MLN122 - FA26 - FE - C1",
        url="https://fuexam.me/threads/1473/",
        term="FA26",
        exam_type=ExamType.FE,
        platform="fuexam",
        crop_layout="fuexam_2026",
    )
    # Giả lập 5 câu: 2 câu có đáp án từ comments (WEAK), 3 câu '?' (NO_DATA)
    questions_c1 = []
    answers_map_c1 = {}
    for idx in range(1, 6):
        q = Question(
            id=100 + idx,
            exam_id=exam_c1.id,
            index=idx,
            local_image_path=str(mock_fuexam_env["sample_img"]),
        )
        if idx <= 2:
            ans = Answer(
                id=100 + idx,
                question_id=q.id,
                answer_set=["A"],
                status=AnswerStatus.WEAK,
                confidence=0.5,
                vote_breakdown={"_source": "comments", "A": 1},
            )
        else:
            ans = Answer(
                id=100 + idx,
                question_id=q.id,
                answer_set=["?"],
                status=AnswerStatus.NO_DATA,
                confidence=0.0,
                vote_breakdown={"_source": "no_data"},
            )
        q.answer = ans
        questions_c1.append(q)
        answers_map_c1[q.id] = ans

    docx_c1 = build_exam_docx(
        subject_code=subject_code,
        exam=exam_c1,
        questions=questions_c1,
        output_dir=exam_dir,
        cropped_dir=mock_fuexam_env["tmp_path"] / "images",
        platform="fuexam",
        add_question_number=False,
        add_divider=True,
        answers_map=answers_map_c1,
    )

    # 2. Thread 1474 (C2)
    exam_c2 = Exam(
        id=1474,
        title="MLN122 - FA26 - FE - C2",
        url="https://fuexam.me/threads/1474/",
        term="FA26",
        exam_type=ExamType.FE,
        platform="fuexam",
        crop_layout="fuexam_2026",
    )
    # Giả lập 5 câu: 4 câu CONFIDENT, 1 câu CONFLICT
    questions_c2 = []
    answers_map_c2 = {}
    for idx in range(1, 6):
        q = Question(
            id=200 + idx,
            exam_id=exam_c2.id,
            index=idx,
            local_image_path=str(mock_fuexam_env["sample_img"]),
        )
        if idx <= 4:
            ans = Answer(
                id=200 + idx,
                question_id=q.id,
                answer_set=["B"],
                status=AnswerStatus.CONFIDENT,
                confidence=0.9,
                vote_breakdown={"_source": "comments", "B": 3},
            )
        else:
            ans = Answer(
                id=200 + idx,
                question_id=q.id,
                answer_set=["C"],
                status=AnswerStatus.CONFLICT,
                confidence=0.4,
                vote_breakdown={"_source": "comments", "C": 2, "D": 2},
            )
        q.answer = ans
        questions_c2.append(q)
        answers_map_c2[q.id] = ans

    docx_c2 = build_exam_docx(
        subject_code=subject_code,
        exam=exam_c2,
        questions=questions_c2,
        output_dir=exam_dir,
        cropped_dir=mock_fuexam_env["tmp_path"] / "images",
        platform="fuexam",
        add_question_number=False,
        add_divider=True,
        answers_map=answers_map_c2,
    )

    # Kiểm tra tên file và không đè nhau
    expected_c1 = "MLN122 - FUE - FA26 - FE - C1.docx"
    expected_c2 = "MLN122 - FUE - FA26 - FE - C2.docx"
    assert docx_c1.name == expected_c1
    assert docx_c2.name == expected_c2
    assert docx_c1.name != docx_c2.name
    assert docx_c1.exists()
    assert docx_c2.exists()

    # Kiểm tra metadata C1
    meta_c1_path = exam_dir / f"{expected_c1}.meta.json"
    assert meta_c1_path.exists()
    meta_c1 = json.loads(meta_c1_path.read_text(encoding="utf-8"))
    assert meta_c1["thread_id"] == 1473
    assert meta_c1["source_url"] == "https://fuexam.me/threads/1473/"
    assert meta_c1["weak_count"] == 2
    assert meta_c1["no_data_count"] == 3
    assert meta_c1["confident_count"] == 0
    # Công thức: confident + weak + conflict + ai + no_data = total_questions
    assert meta_c1["confident_count"] + meta_c1["weak_count"] + meta_c1["conflict_count"] + meta_c1["ai_count"] + meta_c1["no_data_count"] == meta_c1["questions_count"]
    # Mọi câu '?' (3, 4, 5) phải nằm trong review_needed_questions
    for q_idx in [3, 4, 5]:
        assert q_idx in meta_c1["review_needed_questions"]

    # Kiểm tra metadata C2
    meta_c2_path = exam_dir / f"{expected_c2}.meta.json"
    assert meta_c2_path.exists()
    meta_c2 = json.loads(meta_c2_path.read_text(encoding="utf-8"))
    assert meta_c2["thread_id"] == 1474
    assert meta_c2["source_url"] == "https://fuexam.me/threads/1474/"
    assert meta_c2["confident_count"] == 4
    assert meta_c2["conflict_count"] == 1
    assert meta_c2["no_data_count"] == 0
    assert meta_c2["confident_count"] + meta_c2["weak_count"] + meta_c2["conflict_count"] + meta_c2["ai_count"] + meta_c2["no_data_count"] == meta_c2["questions_count"]
    assert 5 in meta_c2["review_needed_questions"]


def test_fuexam_overwrite_protection_different_thread(mock_fuexam_env):
    """
    Test cổng bảo vệ ghi đè: Từ chối ghi đè nếu file đã tồn tại và thuộc thread khác.
    """
    subject_code = "TEST101"
    exam_dir = mock_fuexam_env["out_base"] / subject_code
    exam_dir.mkdir(parents=True, exist_ok=True)

    # 1. Thread 101 tạo file trước
    exam_1 = Exam(
        id=101,
        title="TEST101 - FA26 - FE",
        url="https://fuexam.me/threads/101/",
        term="FA26",
        exam_type=ExamType.FE,
        platform="fuexam",
    )
    questions = [
        Question(id=1, exam_id=101, index=1, local_image_path=str(mock_fuexam_env["sample_img"]))
    ]
    answers_map = {
        1: Answer(id=1, question_id=1, answer_set=["A"], status=AnswerStatus.CONFIDENT, confidence=1.0, vote_breakdown={"_source": "image"})
    }
    p1 = build_exam_docx(
        subject_code=subject_code,
        exam=exam_1,
        questions=questions,
        output_dir=exam_dir,
        platform="fuexam",
        answers_map=answers_map,
    )
    assert p1.exists()

    # 2. Thread 102 cố ý ghi ra cùng tên file
    exam_2 = Exam(
        id=102,
        title="TEST101 - FA26 - FE",
        url="https://fuexam.me/threads/102/",
        term="FA26",
        exam_type=ExamType.FE,
        platform="fuexam",
    )
    questions_2 = [
        Question(id=2, exam_id=102, index=1, local_image_path=str(mock_fuexam_env["sample_img"]))
    ]
    answers_map_2 = {
        2: Answer(id=2, question_id=2, answer_set=["B"], status=AnswerStatus.CONFIDENT, confidence=1.0, vote_breakdown={"_source": "image"})
    }

    with pytest.raises(RuntimeError) as exc_info:
        build_exam_docx(
            subject_code=subject_code,
            exam=exam_2,
            questions=questions_2,
            output_dir=exam_dir,
            platform="fuexam",
            answers_map=answers_map_2,
        )

    assert "xung đột ghi đè" in str(exc_info.value).lower()
    assert "Thread 101" in str(exc_info.value)
    assert "Thread 102" in str(exc_info.value)


def test_term_from_thread_title_overrides_image_filename(mock_fuexam_env):
    """
    Test danh tính đề lấy từ TIÊU ĐỀ THREAD, không từ tên file ảnh:
    Nếu tiêu đề thread là FA26 nhưng file ảnh có chứa 'sp26',
    kỳ và tên file Word vẫn phải là FA26.
    """
    subject_code = "MLN122"
    exam_dir = mock_fuexam_env["out_base"] / subject_code
    exam_dir.mkdir(parents=True, exist_ok=True)

    # Giả lập file ảnh có tên chứa SP26
    sp26_img = mock_fuexam_env["tmp_path"] / "mln122-sp26-fe-c1_001-webp.png"
    im = Image.new("RGB", (300, 150), color=(255, 255, 255))
    im.save(sp26_img)

    exam = Exam(
        id=1473,
        title="MLN122 - FA26 - FE - C1",
        url="https://fuexam.me/threads/1473/",
        term="FA26",
        exam_type=ExamType.FE,
        platform="fuexam",
    )
    q = Question(
        id=1,
        exam_id=exam.id,
        index=1,
        file_name="mln122-sp26-fe-c1_001.webp",
        local_image_path=str(sp26_img),
    )
    ans = Answer(
        id=1,
        question_id=1,
        answer_set=["A"],
        status=AnswerStatus.CONFIDENT,
        confidence=1.0,
        vote_breakdown={"_source": "image"},
    )
    q.answer = ans

    docx_path = build_exam_docx(
        subject_code=subject_code,
        exam=exam,
        questions=[q],
        output_dir=exam_dir,
        platform="fuexam",
        answers_map={1: ans},
    )

    # Tên file phải theo tiêu đề thread FA26, không dùng SP26 từ tên file ảnh
    assert docx_path.name == "MLN122 - FUE - FA26 - FE - C1.docx"
    assert "SP26" not in docx_path.name
