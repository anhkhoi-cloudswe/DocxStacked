import pytest
from pathlib import Path
from backend.app.db.models import Exam
from backend.app.modules.export.docx_builder import format_exam_docx_filename, normalize_term


def test_normalize_term():
    assert normalize_term("SU 2024") == "SU24"
    assert normalize_term("Summer 2024") == "SU24"
    assert normalize_term("Fall 2024") == "FA24"
    assert normalize_term("FA 2025") == "FA25"
    assert normalize_term("Spring 2026") == "SP26"
    assert normalize_term("SP26") == "SP26"
    assert normalize_term("Winter 2023") == "WI23"
    assert normalize_term("WI24") == "WI24"


def test_format_exam_docx_filename_fuoverflow():
    exam = Exam(
        id=101,
        title="PRM393 SU 2024 FE (Thread 123)",
        term="SU 2024",
        exam_type="FE",
        platform="fuoverflow",
    )
    fn = format_exam_docx_filename("PRM393", exam, platform="fuoverflow")
    assert fn == "PRM393 - FUO - SU24 - FE.docx"
    assert "Thread" not in fn


def test_format_exam_docx_filename_fuexam():
    exam = Exam(
        id=941,
        title="PRM393 - SU26 - FE RE (Thread 941)",
        term="SU26",
        exam_type="FE",
        platform="fuexam",
    )
    fn = format_exam_docx_filename("PRM393", exam, platform="fuexam")
    assert fn == "PRM393 - FUE - SU26 - FE - RE.docx"
    assert "Thread" not in fn


def test_format_exam_docx_filename_suffix_order():
    # Suffix order: ... - {KỲ} - [B5 -] {LOẠI} [- RE] [- {MÃ ĐỀ}].docx
    exam = Exam(
        id=202,
        title="PRM393 Summer 2024 B5 FE RE C1",
        term="",
        exam_type="FE",
        platform="fuexam",
    )
    fn = format_exam_docx_filename("PRM393", exam, platform="fuexam")
    assert fn == "PRM393 - FUE - SU24 - B5 - FE - RE - C1.docx"


def test_format_exam_docx_filename_no_collision_between_platforms():
    # Same subject, same term, same type
    exam_fuo = Exam(id=1, title="PRM393 SU26 FE", term="SU26", exam_type="FE", platform="fuoverflow")
    exam_fue = Exam(id=2, title="PRM393 SU26 FE", term="SU26", exam_type="FE", platform="fuexam")
    
    fn_fuo = format_exam_docx_filename("PRM393", exam_fuo, platform="fuoverflow")
    fn_fue = format_exam_docx_filename("PRM393", exam_fue, platform="fuexam")
    
    assert fn_fuo == "PRM393 - FUO - SU26 - FE.docx"
    assert fn_fue == "PRM393 - FUE - SU26 - FE.docx"
    assert fn_fuo != fn_fue
    
    # Destination directories are also strictly separated
    dir_fuo = Path("data/output/FUO/PRM393") / fn_fuo
    dir_fue = Path("data/output/FUE/PRM393") / fn_fue
    assert dir_fuo != dir_fue
    assert "FUO" in str(dir_fuo)
    assert "FUE" in str(dir_fue)


def test_format_exam_docx_filename_unrecognized_term():
    exam = Exam(
        id=303,
        title="PRM393 Đề thi Final Term 3 (Thread 555)",
        term="",
        exam_type="FE",
    )
    fn = format_exam_docx_filename("PRM393", exam, platform="fuoverflow")
    assert "Thread" not in fn
    assert fn.startswith("PRM393 - FUO - ")
    assert hasattr(exam, "warning") and exam.warning
