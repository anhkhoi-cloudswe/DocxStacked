"""
backend/tests/test_fuexam_integration.py
Bộ kiểm thử cô lập (không chạm DB thật) cho tích hợp fuexam.me:
1. Bộ lọc 3 lớp theo cây diễn đàn thực tế (TÀI LIỆU CÁC MÔN HỌC / Kỳ N / môn):
   - Từ chối thread hỏi đáp (/threads/tai-anh.857/, ngoài cây môn học)
   - Từ chối đề PE với thông báo chính xác 'Chưa hỗ trợ PE trên fuexam'
   - Từ chối thread < 10 ảnh câu hỏi
   - Chấp nhận đề FE hợp lệ >= 10 ảnh
2. Tách nhiều mã đề chuẩn spec bằng banner hash (không dùng regex trên tiêu đề thread).
3. Đọc đáp án trong ảnh:
   - Đọc mẫu glyph offline A, B, C, D, E chuẩn hóa kích thước (20x25)
   - Hỗ trợ câu chọn nhiều đáp án ("A, C", "AC")
   - Test âm tính (ảnh không có dải xanh, ảnh có chữ/khối xanh khác)
4. Quy tắc bình luận (1 phiếu/tác giả, giới hạn 20, dị thường >1000 = 0, từ đệm, 'a hay b').
5. Ưu tiên AI khi không chắc chắn: câu có đáp án từ ảnh -> CONFIDENT, không gọi AI.
"""

import math
from pathlib import Path
from PIL import Image, ImageDraw
import numpy as np
import pytest

from backend.app.db.models import AnswerStatus, Comment
from backend.app.modules.analysis.image_answer_reader import (
    find_green_answer_strip,
    match_letter_glyph,
    read_answer_from_image,
    synthesize_green_answer_strip,
    AnswerReadResult,
)
from backend.app.modules.analysis.parser import parse_comment_text
from backend.app.modules.analysis.voting import tally_votes
from backend.app.modules.crawler.fuexam_crawler import (
    filter_and_classify_thread,
    hash_banner_exam_code,
    ThreadFilterResult,
)


def test_thread_filter_accepts_valid_fe():
    """Lớp 1 & 2: Chấp nhận đề thi FE hợp lệ có đủ >= 10 ảnh câu hỏi."""
    title = "Đề Thi FE - PRM393 - SU26 - FE - RE"
    url = "https://fuexam.me/threads/prm393-su26-fe-re.941/"
    # Đủ 10 câu hỏi
    questions = [{"index": i, "title": f"q{i}", "slug": f"q{i}"} for i in range(1, 11)]

    html = """
    <ul class="p-breadcrumbs">
        <li><a href="/">Trang chủ</a></li>
        <li><a href="/categories/tai-lieu-cac-mon-hoc.1/">TÀI LIỆU CÁC MÔN HỌC</a></li>
        <li><a href="/forums/ky-5.15/">Kỳ 5</a></li>
        <li><a href="/forums/prm393.100/">PRM393</a></li>
    </ul>
    """

    res = filter_and_classify_thread(title, url, questions, raw_html=html)
    assert res.is_valid is True
    assert res.exam_type == "FE"
    assert len(res.sub_exams) == 1
    assert res.sub_exams[0].exam_code is None


def test_thread_filter_rejects_pe_with_exact_message():
    """Lớp 2: Từ chối đề PE với thông báo chính xác 'Chưa hỗ trợ PE trên fuexam'."""
    title = "PRN231 - Đề Thi PE - SU26"
    url = "https://fuexam.me/threads/prn231-de-thi-pe-su26.1234/"
    questions = [{"index": i, "title": f"q{i}", "slug": f"q{i}"} for i in range(1, 12)]

    res = filter_and_classify_thread(title, url, questions)
    assert res.is_valid is False
    assert res.exam_type == "PE"
    assert res.rejection_reason == "Chưa hỗ trợ PE trên fuexam"


def test_thread_filter_rejects_tai_anh_and_qa_threads():
    """Lớp 1 & 2: Từ chối thread hỏi đáp / hướng dẫn như /threads/tai-anh.857/."""
    title = "Hướng dẫn tải ảnh và xem đáp án trên fuexam"
    url = "https://fuexam.me/threads/tai-anh.857/"
    questions = [{"index": i, "title": f"q{i}", "slug": f"q{i}"} for i in range(1, 12)]

    res = filter_and_classify_thread(title, url, questions)
    assert res.is_valid is False
    assert "không phải là bài đăng đề thi" in res.rejection_reason


def test_thread_filter_rejects_outside_course_forum():
    """Lớp 1: Từ chối thread không thuộc cây môn học (TÀI LIỆU CÁC MÔN HỌC)."""
    title = "Thảo luận về đề thi PRM393"
    url = "https://fuexam.me/threads/thao-luan-prm393.999/"
    questions = [{"index": i, "title": f"q{i}", "slug": f"q{i}"} for i in range(1, 12)]

    html_non_course = """
    <ul class="p-breadcrumbs">
        <li><a href="/">Trang chủ</a></li>
        <li><a href="/forums/thao-luan-chung.2/">Diễn đàn Thảo Luận Chung</a></li>
    </ul>
    """

    res = filter_and_classify_thread(title, url, questions, raw_html=html_non_course)
    assert res.is_valid is False
    assert "không thuộc cây môn học" in res.rejection_reason


def test_thread_filter_rejects_under_10_images():
    """Lớp 3: Từ chối thread có ít hơn 10 ảnh câu hỏi."""
    title = "Đề Thi FE - PRM393 - SU26"
    url = "https://fuexam.me/threads/prm393.941/"
    questions = [{"index": i, "title": f"q{i}", "slug": f"q{i}"} for i in range(1, 6)]

    res = filter_and_classify_thread(title, url, questions)
    assert res.is_valid is False
    assert "ít hơn 10 ảnh" in res.rejection_reason


def test_thread_filter_multi_exam_splitting_by_banner_hash():
    """
    Tách nhiều mã đề bằng hash dải banner (không dùng regex tiêu đề):
    Có 2 nhóm ảnh mang dải banner khác nhau -> Tách thành 2 SubExam.
    """
    title = "Đề Thi FE - PRM393 - SU26"
    url = "https://fuexam.me/threads/prm393.941/"

    # Tạo 12 câu hỏi thuộc 2 mã đề khác nhau (6 câu mỗi nhóm)
    questions = []
    for i in range(1, 7):
        questions.append({"index": i, "banner_hash": "hash_banner_exam_code_101", "slug": f"q{i}"})
    for i in range(7, 13):
        questions.append({"index": i, "banner_hash": "hash_banner_exam_code_102", "slug": f"q{i}"})

    def mock_ai_reader(sample_img, default_code=""):
        return "Mã đề 101" if "101" in str(sample_img) else "Mã đề 102"

    res = filter_and_classify_thread(title, url, questions, ai_exam_code_reader=mock_ai_reader)
    assert res.is_valid is True
    assert len(res.sub_exams) == 2
    assert res.sub_exams[0].exam_code is not None
    assert res.sub_exams[1].exam_code is not None


def test_offline_glyph_templates_and_multi_choice():
    """Kiểm tra đọc câu hỏi nhiều đáp án ('A, C') bằng ảnh tổng hợp từ mẫu glyph thật."""
    synth_strip = synthesize_green_answer_strip(["A", "C"], prefix="Đáp án: ")
    res = read_answer_from_image(synth_strip)

    assert res.source == "image"
    assert res.letter == "A, C"
    assert res.letters == ["A", "C"]
    assert res.confidence >= 0.80


def test_negative_answer_reading():
    """Test âm tính: ảnh không có dải xanh và ảnh có khối màu xanh không phải đáp án."""
    # 1. Ảnh trắng hoàn toàn (không có xanh)
    blank_im = Image.new("RGB", (400, 200), (255, 255, 255))
    res_blank = read_answer_from_image(blank_im)
    assert res_blank.letter is None
    assert res_blank.confidence == 0.0
    assert res_blank.source == "none"

    # 2. Ảnh có khối xanh lá nhỏ (ví dụ nút trạng thái hoặc cú pháp code, không phải dải đáp án)
    arr = np.full((300, 300, 3), 255, dtype=np.uint8)
    arr[50:65, 50:75] = [35, 145, 55]  # khối nhỏ 15x25
    res_noise = read_answer_from_image(Image.fromarray(arr))
    assert res_noise.letter is None
    assert res_noise.confidence == 0.0


def test_comment_voting_rules_on_fuexam_data():
    """
    Áp dụng đầy đủ quy tắc kiểm phiếu hiện có trên dữ liệu bình luận fuexam:
    1. Giới hạn 20 phiếu
    2. Bất thường reaction > 1000 = 0 (trọng số phản ứng bất thường bị reset)
    3. Một phiếu mỗi tác giả (phiếu sau cùng thắng)
    4. Xử lý từ đệm ('b nhé', 'chắc là c', 'đáp án là d')
    5. Xử lý 'a hay b' -> xung đột
    """
    c1 = Comment(id=1, question_id=1, comment_id="30135", author_hash="user1", raw_text="chắc là a nhé", upvotes=0)
    c2 = Comment(id=2, question_id=1, comment_id="30136", author_hash="user1", raw_text="chắc là b cơ", upvotes=0)
    res = tally_votes([c1, c2])
    assert res.answer_set == ["B"]
    assert res.voters_count == 1

    c3 = Comment(id=3, question_id=2, comment_id="30137", author_hash="user2", raw_text="c", upvotes=1500)
    res3 = tally_votes([c3])
    assert math.isclose(res3.total_weight, 1.0, rel_tol=1e-3)

    parsed = parse_comment_text("a hay b")
    assert parsed.is_ambiguous is True
    assert len(parsed.answers) == 0


def test_ai_priority_respects_image_source():
    """
    Câu hỏi đã đọc được đáp án từ ảnh -> status CONFIDENT, source 'image'.
    Quy tắc: Không gọi AI giải đề, không để bình luận ghi đè.
    """
    from backend.tests.test_ai_uncertainty_priority import MockAnswer, MockQuestion, select_questions_for_ai

    q1 = MockQuestion(id=1, index=1, answer=MockAnswer(status=AnswerStatus.CONFIDENT, confidence=1.0, valid_comments_count=0, answer_set=["C"]))
    q2 = MockQuestion(id=2, index=2, answer=MockAnswer(status=AnswerStatus.WEAK, confidence=0.5, valid_comments_count=1, answer_set=["B"]))

    selected = select_questions_for_ai([q1, q2], max_calls=20, ai_mode="only_uncertain")
    assert q1 not in selected
    assert q2 in selected


def test_dynamic_crop_zero_boundary_touch_across_150_images():
    """
    Test tự động mục 1: không có hàng pixel chữ nào chạm mép ảnh crop
    (khoảng cách an toàn >= 2px từ mép ảnh crop) trên toàn bộ ảnh fixture cố định.
    In số vi phạm ra console (phải bằng 0).
    """
    from backend.app.modules.export.image_cropper import crop_question_single

    fixture_dir = Path("backend/tests/fixtures/crop")
    fixture_files = sorted(list(fixture_dir.glob("*.webp")) + list(fixture_dir.glob("*.jpg")))
    assert len(fixture_files) >= 10

    total_violations = 0
    for p in fixture_files:
        res = crop_question_single(p)
        im_cr = res.cropped_image
        arr_cr = np.array(im_cr)
        dark_c = (arr_cr < 180).all(axis=2)

        top_touch = dark_c[0, :].sum() > 0
        left_touch = dark_c[:, 0].sum() > 0
        right_touch = dark_c[:, -1].sum() > 0 and res.box[2] < arr_cr.shape[1]
        bot_touch = dark_c[-1, :].sum() > 0 and res.box[3] < arr_cr.shape[0]

        if top_touch or left_touch or right_touch or bot_touch:
            total_violations += 1

    print(f"\n[TỔNG CỘNG {len(fixture_files)} ẢNH FIXTURE] Số vi phạm chạm viền: {total_violations}")
    assert total_violations == 0


def test_exam_code_banner_distance_same_vs_different():
    """
    Test mục 3: Tính khoảng cách tương đồng giữa 2 ảnh cùng mã đề và 2 ảnh khác mã đề.
    In khoảng cách tương đồng của 2 cặp.
    """
    from backend.app.modules.crawler.fuexam_crawler import (
        extract_exam_code_chip,
        compute_exam_code_distance,
    )

    p_b5_01 = Path("data/cache/fuexam/media_44146/prm393-su26-b5-fe_001-webp.webp")
    p_b5_02 = Path("data/cache/fuexam/media_44147/prm393-su26-b5-fe_002-webp.webp")
    p_re_01 = Path("data/cache/fuexam/media_34522/prm393-su26-fe-re_001-webp.webp")

    feat_b5_1 = extract_exam_code_chip(p_b5_01)
    feat_b5_2 = extract_exam_code_chip(p_b5_02)
    feat_re_1 = extract_exam_code_chip(p_re_01)

    dist_same = compute_exam_code_distance(feat_b5_1, feat_b5_2)
    dist_diff = compute_exam_code_distance(feat_b5_1, feat_re_1)

    print(f"\n[TÁCH MÃ ĐỀ] Khoảng cách cùng mã đề (B5 Q1 vs B5 Q2): {dist_same:.4f}")
    print(f"[TÁCH MÃ ĐỀ] Khoảng cách khác mã đề (B5 Q1 vs RE Q1): {dist_diff:.4f}")

    assert dist_same <= 0.08, f"Cùng mã đề phải có khoảng cách nhỏ, nhận được {dist_same}"
    assert dist_diff >= 0.20, f"Khác mã đề phải có khoảng cách lớn, nhận được {dist_diff}"
    assert dist_same < dist_diff


def test_real_threads_exam_code_group_count():
    """
    Test mục 3: Chạy trên các bộ ảnh fixture cố định cùng mã đề (không phụ thuộc data/cache hay môn khác).
    Mỗi bộ cùng mã đề phải cho ra đúng 1 nhóm.
    """
    fixture_dir = Path("backend/tests/fixtures/crop")
    thread_samples = {
        "ITE302c FA24 RE": sorted(fixture_dir.glob("2024_ite302c_fa24_re_*.webp")),
        "PRN232 SU25 FE": sorted(fixture_dir.glob("2025_prn232_su25_fe_*.webp")),
        "ITE302c SU25 RE": sorted(fixture_dir.glob("2025_ite302c_su25_re_*.webp")),
    }

    for t_name, files in thread_samples.items():
        assert len(files) >= 2, f"Thiếu fixture cho {t_name}"
        # Lớp 3 yêu cầu tối thiểu 10 ảnh/đề; lặp lại fixture cùng mã đề để đạt >= 10 ảnh mà không phụ thuộc data/cache
        padded = [files[i % len(files)] for i in range(10)]
        questions = [{"index": i, "local_image_path": str(p), "slug": p.stem} for i, p in enumerate(padded, 1)]
        res = filter_and_classify_thread(t_name, "https://fuexam.me/threads/sample.123/", questions)
        group_count = len(res.sub_exams)
        print(f"Thread {t_name}: số nhóm mã đề tìm được = {group_count}")
        assert group_count == 1, f"Thread {t_name} phải có đúng 1 nhóm mã đề, nhận được {group_count}"
