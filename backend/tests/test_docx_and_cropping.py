from pathlib import Path
from PIL import Image
import pytest
from docx import Document
from docx.shared import Cm, Pt, RGBColor

from backend.app.db.models import Answer, AnswerStatus, Exam, Question, QuestionType
from backend.app.modules.export.docx_builder import build_exam_docx, format_exam_docx_filename
from backend.app.modules.export.image_cropper import crop_question_image


def test_format_exam_docx_filename():
    exam = Exam(
        subject_id=1,
        title="CSD202 - SU26 - FE",
        term="SU26",
        url="https://fuoverflow.com/threads/123/",
    )
    name = format_exam_docx_filename("CSD202", exam)
    assert name == "CSD202 - SU26 - FE.docx"
    assert "CSD202_CSD202" not in name

    # Test preserving RE (Retake) in title
    exam_re = Exam(
        subject_id=322,
        title="PRM392 - SP26 - RE",
        term="SP26",
        url="https://fuoverflow.com/threads/6953/",
    )
    name_re = format_exam_docx_filename("PRM392", exam_re)
    assert name_re == "PRM392 - SP26 - RE.docx"
    assert "FE" not in name_re

    # Test with title missing subject code
    exam_partial = Exam(
        subject_id=322,
        title="SP 2024 - RE",
        term="SP24",
        url="https://fuoverflow.com/threads/6954/",
    )
    name_partial = format_exam_docx_filename("PRM392", exam_partial)
    assert name_partial == "PRM392 - SP 2024 - RE.docx"


def test_crop_synthetic_image(tmp_path: Path):
    # Create synthetic 1920x720 image with blue banner and content
    im = Image.new("RGB", (1920, 720), (255, 255, 255))
    pixels = im.load()
    # Blue top banner (y 0..30)
    for y in range(30):
        for x in range(1920):
            pixels[x, y] = (0, 100, 200)

    # Question text (x: 50..350, y: 60..160)
    for y in range(60, 160):
        for x in range(50, 350):
            pixels[x, y] = (10, 10, 10)

    input_file = tmp_path / "raw.png"
    output_file = tmp_path / "cropped.png"
    im.save(input_file)

    cropped, success = crop_question_image(input_file, output_file, margin=12)
    assert success is True
    assert output_file.exists()
    assert cropped.size[0] >= 300
    assert cropped.size[1] >= 100
    # Cropped height should be around 100 + 24 margin, not 720
    assert cropped.size[1] < 200


def test_docx_builder_structure(tmp_path: Path):
    output_dir = tmp_path / "output"
    cropped_dir = tmp_path / "cropped"

    # Create synthetic question image
    img_path = tmp_path / "q1.png"
    im = Image.new("RGB", (600, 300), (255, 255, 255))
    im.save(img_path)

    exam = Exam(
        id=99,
        subject_id=1,
        title="CSD202 - SU26 - FE",
        term="SU26",
        url="https://fuoverflow.com/threads/123/",
    )
    q1 = Question(
        id=1,
        exam_id=99,
        index=1,
        file_name="Q1.webp",
        qtype=QuestionType.SINGLE,
        local_image_path=str(img_path),
    )
    q1.answer = Answer(
        question_id=1,
        answer_set=["B"],
        status=AnswerStatus.CONFIDENT,
    )

    docx_path = build_exam_docx(
        subject_code="CSD202",
        exam=exam,
        questions=[q1],
        output_dir=output_dir,
        cropped_dir=cropped_dir,
    )

    assert docx_path.exists()
    assert docx_path.name == "CSD202 - SU26 - FE.docx"

    doc = Document(str(docx_path))
    section = doc.sections[0]
    # Verify Letter size (approx 21.59 x 27.94 cm)
    assert round(section.page_width.cm, 2) == 21.59
    assert round(section.page_height.cm, 2) == 27.94
    assert round(section.left_margin.cm, 2) == 2.54

    # 1 question = 1 question header ('Câu 1:') + 1 image + 1 answer ('B') + 1 divider ('===')
    assert len(doc.paragraphs) == 4
    num_p = doc.paragraphs[0]
    assert num_p.text == "Câu 1:"
    assert num_p.runs[0].bold is True

    ans_p = doc.paragraphs[2]
    assert ans_p.text == "B"
    run = ans_p.runs[0]
    assert run.bold is True
    assert run.font.size == Pt(20)
    assert run.font.color.rgb == RGBColor(0xEE, 0x00, 0x00)

    # Paragraph 3 is the horizontal divider paragraph
    div_p = doc.paragraphs[3]
    assert div_p._p.pPr is not None
    assert div_p._p.pPr.find("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}pBdr") is not None
