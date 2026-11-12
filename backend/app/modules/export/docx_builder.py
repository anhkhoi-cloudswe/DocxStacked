import io
import re
from pathlib import Path
from typing import List, Optional
from PIL import Image
from docx import Document
from docx.shared import Cm, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.db.models import Answer, AnswerStatus, Exam, Question
from backend.app.modules.export.image_cropper import crop_question_image

logger = get_logger(__name__)
settings = get_settings()


def format_exam_docx_filename(subject_code: str, exam: Exam) -> str:
    """
    Format filename matching the original exam title or structured '{MaMon} - {Kỳ} - {Type}.docx'.
    Preserves exact designations like 'RE' (Retake) vs 'FE', e.g. 'PRM392 - SP26 - RE.docx'.
    """
    code = subject_code.upper().strip()
    raw_title = (exam.title or "").strip()

    if raw_title:
        # Clean characters not allowed in Windows filenames: \ / : * ? " < > |
        cleaned = re.sub(r'[\\/*?:"<>|]', "", raw_title).strip()
        # Remove trailing .docx if present in title
        if cleaned.lower().endswith(".docx"):
            cleaned = cleaned[:-5].strip()

        # Eliminate repetitive duplicate subject prefix like 'CSD202_CSD202' or 'CSD202 - CSD202'
        dup_pattern = rf"^{re.escape(code)}[_\-\s]+{re.escape(code)}[_\-\s]+"
        cleaned = re.sub(dup_pattern, f"{code} - ", cleaned, flags=re.IGNORECASE)

        # Ensure the filename starts with subject code if missing
        if not cleaned.upper().startswith(code):
            cleaned = f"{code} - {cleaned}"

        return f"{cleaned}.docx"

    term = exam.term
    if not term and exam.title:
        m = re.search(r"\b(SU|FA|SP|WI)\d{2}\b", exam.title, re.IGNORECASE)
        if m:
            term = m.group(0).upper()
    term_str = term if term else "SU26"
    e_type = exam.exam_type.value if hasattr(exam.exam_type, "value") else (str(exam.exam_type) if exam.exam_type else "FE")
    return f"{code} - {term_str} - {e_type}.docx"


def _render_question_to_doc(
    doc: Document,
    q: Question,
    cropped_dir: Path,
    highlight_check_needed: bool = True,
    answer_format: str = "letter_keyword",
    add_divider: bool = True,
    add_question_number: bool = True,
) -> None:
    # 0. Question Number Header (e.g. "Câu 1:")
    if add_question_number:
        num_paragraph = doc.add_paragraph()
        num_paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        num_paragraph.paragraph_format.space_before = Pt(8)
        num_paragraph.paragraph_format.space_after = Pt(2)
        run_num = num_paragraph.add_run(f"Câu {q.index}:")
        run_num.bold = True
        run_num.font.size = Pt(13)
        run_num.font.color.rgb = RGBColor(0x11, 0x18, 0x27)

    # A. Cropped Image Paragraph
    img_paragraph = doc.add_paragraph()
    img_paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    img_paragraph.paragraph_format.space_before = Pt(2 if add_question_number else 6)
    img_paragraph.paragraph_format.space_after = Pt(4)

    img_inserted = False
    if q.local_image_path:
        raw_p = Path(q.local_image_path)
        full_raw_path = raw_p if raw_p.is_absolute() else (settings.BASE_DIR / raw_p)
        if full_raw_path.exists() and full_raw_path.stat().st_size > 0:
            try:
                # Save / retrieve cropped PNG (q001.png, q002.png...)
                cropped_filename = f"q{q.index:03d}.png"
                cropped_path = cropped_dir / cropped_filename

                need_crop = True
                if cropped_path.exists():
                    # If cropped image exists, verify it is fresher than raw and not a stale thumbnail crop
                    if full_raw_path.stat().st_mtime <= cropped_path.stat().st_mtime and cropped_path.stat().st_size > 1500:
                        try:
                            test_crop = Image.open(cropped_path)
                            if test_crop.height > 150:
                                cropped_img = test_crop
                                need_crop = False
                        except Exception:
                            need_crop = True

                if need_crop:
                    try:
                        cropped_img, _ = crop_question_image(
                            input_path=full_raw_path,
                            output_path=cropped_path,
                            margin=12,
                        )
                    except Exception as crop_err:
                        logger.warning(f"Cropping failed for {full_raw_path.name}: {crop_err}. Using original image.")
                        cropped_img = Image.open(full_raw_path)
                        cropped_path = full_raw_path

                # Scale image at 120 dpi (max 16.51 cm width)
                img_w_px = cropped_img.width
                width_cm = min(16.51, (img_w_px / 120.0) * 2.54)

                # Insert cropped PNG (or raw image fallback)
                img_paragraph.add_run().add_picture(str(cropped_path), width=Cm(width_cm))
                img_inserted = True
            except Exception as img_err:
                logger.warning(f"Error cropping/inserting image for Q{q.index} ({full_raw_path}): {img_err}")

    if not img_inserted:
        run_missing = img_paragraph.add_run(f"[Ảnh câu {q.index}]")
        run_missing.font.size = Pt(11)
        run_missing.font.italic = True
        run_missing.font.color.rgb = RGBColor(0x8C, 0x82, 0x78)

    # B. Answer Paragraph
    # Format: Bold 20pt Red #EE0000
    ans_paragraph = doc.add_paragraph()
    ans_paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    ans_paragraph.paragraph_format.space_before = Pt(0)
    ans_paragraph.paragraph_format.space_after = Pt(4 if add_divider else 16)

    # Determine answer text and status
    ans_obj: Optional[Answer] = None
    try:
        if "answer" in q.__dict__:
            ans_obj = q.__dict__["answer"]
        else:
            ans_obj = getattr(q, "answer", None)
    except Exception:
        ans_obj = None

    ans_text = "?"
    status = AnswerStatus.NO_DATA

    options_map = {}
    if ans_obj and ans_obj.vote_breakdown and isinstance(ans_obj.vote_breakdown, dict):
        options_map = ans_obj.vote_breakdown.get("_options", {})

    if ans_obj and ans_obj.answer_set:
        if answer_format == "letter_keyword" and options_map:
            formatted_parts = []
            for letter in ans_obj.answer_set:
                clean_letter = letter.strip().upper()
                kw = options_map.get(clean_letter)
                if kw:
                    formatted_parts.append(f"{clean_letter}. {kw}")
                else:
                    formatted_parts.append(clean_letter)
            ans_text = ", ".join(formatted_parts)
        else:
            ans_text = ", ".join(ans_obj.answer_set)
        status = ans_obj.status
    elif ans_obj and ans_obj.status:
        status = ans_obj.status

    # Answer letter run
    run_ans = ans_paragraph.add_run(ans_text)
    run_ans.bold = True
    run_ans.font.size = Pt(20)
    run_ans.font.color.rgb = RGBColor(0xEE, 0x00, 0x00)  # Teacher Red #EE0000

    # Note run for low-confidence or conflict questions
    if highlight_check_needed and (status in (AnswerStatus.CONFLICT, AnswerStatus.WEAK, AnswerStatus.NO_DATA) or ans_text == "?"):
        run_note = ans_paragraph.add_run(" (cần kiểm tra lại)")
        run_note.bold = False
        run_note.font.size = Pt(11)
        run_note.font.color.rgb = RGBColor(0x7F, 0x7F, 0x7F)  # Muted grey 11pt

    # C. Horizontal Divider (Double Border '===')
    if add_divider:
        div_paragraph = doc.add_paragraph()
        div_paragraph.paragraph_format.space_before = Pt(2)
        div_paragraph.paragraph_format.space_after = Pt(14)
        pBdr = parse_xml(
            f'<w:pBdr {nsdecls("w")}><w:bottom w:val="double" w:sz="12" w:space="4" w:color="auto"/></w:pBdr>'
        )
        div_paragraph._p.get_or_add_pPr().append(pBdr)


def _setup_letter_margins(doc: Document) -> None:
    for section in doc.sections:
        section.page_width = Cm(21.59)
        section.page_height = Cm(27.94)
        section.top_margin = Cm(2.54)
        section.bottom_margin = Cm(2.54)
        section.left_margin = Cm(2.54)
        section.right_margin = Cm(2.54)


def build_exam_docx(
    subject_code: str,
    exam: Exam,
    questions: List[Question],
    output_dir: Optional[Path] = None,
    highlight_check_needed: bool = True,
    cropped_dir: Optional[Path] = None,
    answer_format: str = "letter_keyword",
    add_divider: bool = True,
    add_question_number: bool = True,
) -> Path:
    """
    Build Word (.docx) document following the exact reference style (MLN122, PRN232):
      - Letter page size (21.59 x 27.94 cm), 2.54 cm margins all sides.
      - NO cover page, title, header, table of contents, or decorative boxes.
      - Sequential pairs of: [Question Number 'Câu N:'] -> [Cropped Question Image] -> [Answer in 20pt Bold Red #EE0000] -> [Divider '==='].
      - Images cropped to question/options only (watermark and MULTIPLE CHOICE banner removed).
      - Left-aligned, scaled at 120 dpi (width_cm = px / 120 * 2.54), max 16.51 cm width.
      - Answers:
          * Single: 'B' or 'B. Keyword'
          * Multiple: 'A, C' or 'A. Keyword1, C. Keyword2'
          * No data / unanalyzed: '?'
      - If conflict, weak, or no_data: appends ' (cần kiểm tra lại)' in small 11pt grey.
    """
    logger.info(f"Building Word document for {subject_code} - {exam.title} ({len(questions)} questions)...")

    if output_dir is None:
        output_dir = settings.STORAGE_DIR / "output" / subject_code
    output_dir.mkdir(parents=True, exist_ok=True)

    if cropped_dir is None:
        cropped_dir = settings.STORAGE_DIR / "cropped" / subject_code / f"exam_{exam.id}"
    cropped_dir.mkdir(parents=True, exist_ok=True)

    doc = Document()
    _setup_letter_margins(doc)

    sorted_questions = sorted(questions, key=lambda q: q.index)
    for q in sorted_questions:
        _render_question_to_doc(
            doc=doc,
            q=q,
            cropped_dir=cropped_dir,
            highlight_check_needed=highlight_check_needed,
            answer_format=answer_format,
            add_divider=add_divider,
            add_question_number=add_question_number,
        )

    filename = format_exam_docx_filename(subject_code, exam)
    file_path = output_dir / filename
    doc.save(str(file_path))

    logger.info(f"Generated clean Word document: {file_path} (Size: {file_path.stat().st_size} bytes)")
    return file_path


def build_merged_docx(
    subject_code: str,
    exams_data: list,
    output_dir: Optional[Path] = None,
    highlight_check_needed: bool = True,
    answer_format: str = "letter_keyword",
    add_divider: bool = True,
    add_question_number: bool = True,
) -> Path:
    """
    Build a single merged Word (.docx) containing multiple exams, separated by explicit page breaks.
    """
    code = subject_code.upper().strip()
    logger.info(f"Building merged Word document for {code} ({len(exams_data)} exams)...")

    if output_dir is None:
        output_dir = settings.STORAGE_DIR / "output" / code
    output_dir.mkdir(parents=True, exist_ok=True)

    doc = Document()
    _setup_letter_margins(doc)

    for i, (exam, questions) in enumerate(exams_data):
        if i > 0:
            doc.add_page_break()

        cropped_dir = settings.STORAGE_DIR / "cropped" / code / f"exam_{exam.id}"
        cropped_dir.mkdir(parents=True, exist_ok=True)

        sorted_questions = sorted(questions, key=lambda q: q.index)
        for q in sorted_questions:
            _render_question_to_doc(
                doc=doc,
                q=q,
                cropped_dir=cropped_dir,
                highlight_check_needed=highlight_check_needed,
                answer_format=answer_format,
                add_divider=add_divider,
                add_question_number=add_question_number,
            )

    filename = f"{code} - Merged - FE.docx"
    file_path = output_dir / filename
    doc.save(str(file_path))

    logger.info(f"Generated merged Word document: {file_path} (Size: {file_path.stat().st_size} bytes)")
    return file_path
