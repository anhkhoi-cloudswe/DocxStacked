import difflib
import io
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from PIL import Image
from docx import Document
from docx.shared import Cm, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.db.models import Answer, AnswerStatus, Exam, Question
from backend.app.modules.export.image_cropper import crop_question_image, crop_question_single

logger = get_logger(__name__)

class SettingsProxy:
    def __getattr__(self, name: str):
        return getattr(get_settings(), name)

settings = SettingsProxy()


def normalize_term(term_str: Optional[str]) -> Optional[str]:
    """
    Chuẩn hóa kỳ học sang định dạng XX## (SU26, FA26, SP26; 'SU 2024' -> SU24, 'Fall 2024' -> FA24).
    """
    if not term_str:
        return None
    t = term_str.strip()
    m = re.search(r"\b(SU(?:MMER)?|FA(?:LL)?|SP(?:RING)?|WI(?:NTER)?)\s*(?:20)?(\d{2})\b", t, re.IGNORECASE)
    if m:
        prefix = m.group(1).upper()
        if prefix.startswith("SU"):
            p = "SU"
        elif prefix.startswith("FA"):
            p = "FA"
        elif prefix.startswith("SP"):
            p = "SP"
        elif prefix.startswith("WI"):
            p = "WI"
        else:
            p = prefix[:2]
        yy = m.group(2)
        return f"{p}{yy}"
    return None


def parse_exam_tokens(title: str, subject_code: str) -> Tuple[Optional[str], bool, str, bool, List[str]]:
    """
    Phân tách tiêu đề đề thi thành các thành phần:
    (norm_term, has_b5, exam_type, has_re, trailing_tokens)
    """
    s = (title or "").strip()
    s = re.sub(r"\(?\bThread\s*\d+\b\)?", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r'[\\/*?:"<>|]', "", s).strip()
    s = re.sub(r"^\s*Đề\s*Thi\s*(?:FE|PE)?\s*[-–—:]\s*", "", s, flags=re.IGNORECASE).strip()

    term = normalize_term(s)
    has_b5 = bool(re.search(r"\bB5\b", s, re.IGNORECASE))
    has_re = bool(re.search(r"\b(RE|RETAKE)\b", s, re.IGNORECASE))

    is_pe = bool(re.search(r"\bPE\b", s, re.IGNORECASE))
    exam_type = "PE" if is_pe else "FE"

    # Xóa môn học
    s_clean = re.sub(rf"\b{re.escape(subject_code)}\b", "", s, flags=re.IGNORECASE).strip()
    # Xóa mẫu kỳ học đã đọc
    s_clean = re.sub(r"\b(SU|FA|SP|WI|Summer|Fall|Spring|Winter)\s*\d{2,4}\b", "", s_clean, flags=re.IGNORECASE).strip()
    # Xóa các từ khóa chuẩn B5, RE, RETAKE, FE, PE
    s_clean = re.sub(r"\b(B5|RE|RETAKE|FE|PE)\b", "", s_clean, flags=re.IGNORECASE).strip()

    trailing_tokens: List[str] = []
    if any(d in s for d in ("-", "–", "—")):
        segments = [p.strip() for p in re.split(r"\s*[-–—]\s*", s_clean) if p.strip()]
        for seg in segments:
            seg_c = re.sub(r"^[-\s]+|[-\s]+$", "", seg).strip()
            if seg_c and seg_c.upper() != subject_code.upper():
                trailing_tokens.append(seg_c)
    else:
        words = s_clean.split()
        for w in words:
            w_c = w.strip()
            if w_c and w_c.upper() != subject_code.upper():
                trailing_tokens.append(w_c)

    return term, has_b5, exam_type, has_re, trailing_tokens


def format_exam_docx_filename(
    subject_code: str,
    exam: Exam,
    platform: Optional[str] = None,
    sub_exam_code: Optional[str] = None,
) -> str:
    """
    Quy ước tên file Word:
    - "{MÔN} - FUO - {KỲ} - [B5 -] {LOẠI} [- RE] [- {MÃ ĐỀ/HẬU TỐ}].docx" cho FUOverflow
    - "{MÔN} - FUE - {KỲ} - [B5 -] {LOẠI} [- RE] [- {MÃ ĐỀ/HẬU TỐ}].docx" cho fuexam
    Hậu tố giữ nguyên thứ tự: ... - {KỲ} - [B5 -] {LOẠI} [- RE] [- token đuôi khác].docx
    Kỳ chuẩn hóa XX## (SU26, FA26, SP26; "SU 2024" -> SU24).
    Không bao giờ dùng "(Thread N)" làm tên file.
    Danh tính đề và các token được lấy từ TIÊU ĐỀ THREAD, không từ tên file ảnh.
    """
    code = subject_code.upper().strip()

    # 1. Xác định tag nền tảng: FUE hoặc FUO
    plat = platform or getattr(exam, "platform", None) or ""
    if "fuexam" in str(plat).lower():
        plat_tag = "FUE"
    else:
        plat_tag = "FUO"

    raw_title = (exam.title or "").strip()
    term_from_title, title_b5, title_etype, title_re, trailing = parse_exam_tokens(raw_title, code)

    # 2. Chuẩn hóa Kỳ học XX##
    norm_term = term_from_title or normalize_term(getattr(exam, "term", None))
    if not norm_term:
        m_term = re.search(r"\b(SU|FA|SP|WI)\s*\d{2,4}\b", raw_title, re.IGNORECASE)
        if m_term:
            norm_term = normalize_term(m_term.group(0))
        else:
            m_cust = re.search(r"\b(Kỳ\s*\w+|Term\s*\w+|Semester\s*\w+)\b", raw_title, re.IGNORECASE)
            if m_cust:
                norm_term = re.sub(r"\s+", "", m_cust.group(0)).upper()
                setattr(exam, "warning", f"Không đọc được kỳ học chuẩn XX##; đã sử dụng '{norm_term}' từ tiêu đề thread.")
            else:
                norm_term = "UNKNOWN"
                setattr(exam, "warning", "Không đọc được kỳ học từ tiêu đề đề thi. Vui lòng kiểm tra lại.")

    # 3. Kiểm tra các thành phần hậu tố theo thứ tự: [B5 -] {LOẠI} [- RE] [- token đuôi khác]
    has_b5 = title_b5 or bool(re.search(r"\bB5\b", f"{exam.term or ''} {sub_exam_code or ''}", re.IGNORECASE))
    has_re = title_re or bool(re.search(r"\b(RE|RETAKE)\b", f"{exam.term or ''} {sub_exam_code or ''}", re.IGNORECASE))

    # Loại bài thi {LOẠI}: PE hoặc FE
    e_type_val = exam.exam_type.value if hasattr(exam.exam_type, "value") else str(exam.exam_type or "FE")
    if "PE" in e_type_val.upper() or title_etype == "PE":
        e_type = "PE"
    else:
        e_type = "FE"

    # Hậu tố bổ sung (C1, C2, NO1 HCM, ...)
    if sub_exam_code:
        clean_sub = re.sub(r"\(?\bThread\s*\d+\b\)?", "", sub_exam_code, flags=re.IGNORECASE).strip()
        if clean_sub and clean_sub.upper() not in (code, norm_term, "FE", "PE", "B5", "RE", plat_tag):
            if clean_sub not in trailing:
                trailing.append(clean_sub)

    # 4. Ráp theo chuẩn thứ tự: {MÔN} - {PLAT} - {KỲ} - [B5 -] {LOẠI} [- RE] [- token đuôi khác].docx
    parts = [code, plat_tag, norm_term]
    if has_b5:
        parts.append("B5")
    parts.append(e_type)
    if has_re:
        parts.append("RE")
    for tok in trailing:
        if tok not in parts:
            parts.append(tok)

    return f"{' - '.join(parts)}.docx"


def cluster_text_answers(comments: List[Any], similarity_threshold: float = 0.85) -> Optional[str]:
    """
    Cluster text comments for missing_options questions (fuzzy ratio >= similarity_threshold).
    Picks the most popular cluster and formats as 'Letter. Text' or just 'Text'.
    """
    if not comments:
        return None

    def _clean(t: str) -> str:
        lines = [ln.strip() for ln in t.splitlines() if ln.strip()]
        if lines:
            time_idx = -1
            for i_ln, ln in enumerate(lines):
                if re.search(r"(?:lúc\s+\d{1,2}:\d{2}|\b\d{1,2}\/\d{1,2}\/\d{2,4}\b)", ln, re.IGNORECASE):
                    time_idx = i_ln
                    break
            if time_idx != -1:
                if time_idx + 1 < len(lines):
                    t = " ".join(lines[time_idx + 1:])
                else:
                    t = ""
        s = re.sub(r"\s+", " ", t).strip()
        s = re.sub(r"^[A-D]\s*[\.\:\-\)]\s*", "", s, flags=re.I)
        s = re.sub(r"^(?:đáp án là|chắc là|quy luật kinh tế)\s*", "", s, flags=re.I)
        s = re.sub(r"[\.\,\;\:\!\?]+$", "", s).strip()
        return s

    groups: List[Dict[str, Any]] = []

    for c in comments:
        raw_text = getattr(c, "raw_text", "") or ""
        if not raw_text.strip():
            continue

        m_let = re.match(r"^([A-D])\s*[\.\:\-\)]\s*(.*)$", raw_text.strip(), flags=re.I)
        letter = m_let.group(1).upper() if m_let else None
        cleaned = _clean(raw_text)
        if not cleaned or len(cleaned) < 2:
            continue

        matched_group = None
        for g in groups:
            ratio = difflib.SequenceMatcher(None, g["canonical"].lower(), cleaned.lower()).ratio()
            if ratio >= similarity_threshold:
                matched_group = g
                break

        if matched_group:
            matched_group["count"] += 1
            if letter and not matched_group["letter"]:
                matched_group["letter"] = letter
            # Prefer title-cased or uppercase-starting version (e.g. 'Tuyệt đối...' over 'tuyệt đối...')
            if cleaned[0].isupper() and not matched_group["canonical"][0].isupper():
                matched_group["canonical"] = cleaned
            elif len(cleaned) > len(matched_group["canonical"]) and cleaned[0].isupper() == matched_group["canonical"][0].isupper():
                matched_group["canonical"] = cleaned
        else:
            groups.append({
                "canonical": cleaned,
                "count": 1,
                "letter": letter,
            })

    if not groups:
        return None

    groups.sort(key=lambda g: g["count"], reverse=True)
    top = groups[0]
    canonical_text = top["canonical"].strip()
    if top["letter"]:
        return f"{top['letter']}. {canonical_text}"
    return canonical_text


def is_valid_keyword(
    kw: str,
    is_vietnamese_exam: bool = True,
    option_image_text: Optional[str] = None,
) -> bool:
    """
    Validate keyword for options in Word document.
    Rules:
      - Reject placeholders like 'Không rõ từ hình ảnh', 'unknown', 'unclear', 'n/a'.
      - Keyword must match the text of the corresponding option in the question image crop
        (normalized comparison, case-insensitive).
      - If option_image_text is provided: require normalized kw to match or be contained within
        the normalized option_image_text.
      - Reject English-translated keywords on Vietnamese exams when the option text in image is Vietnamese.
    """
    if not kw or not isinstance(kw, str):
        return False
    kw_strip = kw.strip()
    if not kw_strip:
        return False

    lower = kw_strip.lower()
    placeholders = [
        "không rõ từ hình ảnh",
        "không rõ",
        "chưa rõ",
        "không có thông tin",
        "unknown",
        "unclear",
        "not clear",
        "n/a",
        "none",
    ]
    if any(p in lower for p in placeholders):
        return False

    # Keywords must be concise keyphrases/terms:
    # Standard: <= 4 words, <= 25 chars.
    # On Vietnamese exams, common historical/political terms (e.g. 'đầu thập niên 50 thế kỷ XX') can take up to 7 words / 35 chars.
    words = kw_strip.split()
    max_words = 7 if is_vietnamese_exam else 4
    max_chars = 35 if is_vietnamese_exam else 25
    if len(words) > max_words or len(kw_strip) > max_chars:
        return False
    if any(ch in kw_strip for ch in ['(', ')', '{', '}', ';', '=', '"', "'"]):
        return False

    def _normalize(t: str) -> str:
        s = t.lower()
        s = re.sub(r"^[a-d]\s*[\.\:\-\)]\s*", "", s)
        s = re.sub(r"[^\w\s]", " ", s)
        return " ".join(s.split())

    norm_kw = _normalize(kw)

    # If option text from crop image is provided, verify match
    if option_image_text:
        norm_img_text = _normalize(option_image_text)
        if norm_kw and (norm_kw in norm_img_text or norm_img_text in norm_kw):
            return True
        # If words of norm_kw overlap significantly with norm_img_text
        kw_tokens = set(norm_kw.split())
        img_tokens = set(norm_img_text.split())
        if kw_tokens and (kw_tokens.issubset(img_tokens) or (len(kw_tokens & img_tokens) / len(kw_tokens)) >= 0.7):
            return True
        return False

    # Fallback when option_image_text is not directly supplied:
    if is_vietnamese_exam:
        english_words = {
            "primitive", "accumulation", "capitalist", "production", "costs", "cost",
            "blurred", "surplus", "value", "selling", "price", "actual", "smaller",
            "formation", "greater", "which", "the", "of", "and", "in", "to", "for",
            "with", "on", "at", "by", "from", "law", "economic", "fundamental",
            "absolute", "relative", "transportation", "development", "international",
            "trade", "impact", "bourgeois", "state", "regulation",
        }
        tokens = set(re.findall(r"\b[a-zA-Z]+\b", lower))
        # Reject English keywords (like 'Primitive accumulation')
        if tokens & english_words:
            return False

    return True


def _render_question_to_doc(
    doc: Document,
    q: Question,
    cropped_dir: Path,
    highlight_check_needed: bool = True,
    answer_format: str = "letter_keyword",
    multi_choice_format: str = "comma",
    add_divider: bool = True,
    add_question_number: bool = True,
    use_raw_fallback: bool = False,
    answers_map: Optional[Dict[int, Answer]] = None,
    subject_code: str = "",
    exam_title: str = "",
) -> str:
    # 0. Question Number Header (e.g. "Câu 1:")
    if add_question_number:
        num_paragraph = doc.add_paragraph()
        num_paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        num_paragraph.paragraph_format.space_before = Pt(8)
        num_paragraph.paragraph_format.space_after = Pt(2)
        num_paragraph.paragraph_format.keep_with_next = True
        num_paragraph.paragraph_format.keep_together = True
        run_num = num_paragraph.add_run(f"Câu {q.index}:")
        run_num.bold = True
        run_num.font.size = Pt(13)
        run_num.font.color.rgb = RGBColor(0x11, 0x18, 0x27)

    # A. Cropped Image Paragraph
    img_paragraph = doc.add_paragraph()
    img_paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    img_paragraph.paragraph_format.space_before = Pt(2 if add_question_number else 6)
    img_paragraph.paragraph_format.space_after = Pt(4)
    img_paragraph.paragraph_format.keep_with_next = True
    img_paragraph.paragraph_format.keep_together = True

    img_inserted = False
    if q.local_image_path:
        raw_p = Path(q.local_image_path)
        full_raw_path = raw_p if raw_p.is_absolute() else (settings.BASE_DIR / raw_p)
        if full_raw_path.exists() and full_raw_path.stat().st_size > 0:
            try:
                if use_raw_fallback:
                    raw_fallback_png = cropped_dir / f"q{q.index:03d}_raw_fallback.png"
                    target_img = Image.open(full_raw_path).convert("RGB")
                    target_img.save(raw_fallback_png, format="PNG")
                    target_img_path = raw_fallback_png
                else:
                    # Priority: cropped_dir (freshly cropped by crop_exam_images) > q.cropped_image_path (may be stale)
                    target_img_path = None

                    # 1st priority: check cropped_dir for this question
                    cropped_filename = f"q{q.index:03d}.png"
                    cropped_path = cropped_dir / cropped_filename
                    if cropped_path.exists() and cropped_path.stat().st_size > 500:
                        target_img_path = cropped_path

                    # 2nd priority: pre-saved cropped_image_path on Question model (only if NOT already found in cropped_dir)
                    if not target_img_path and getattr(q, "cropped_image_path", None):
                        cand_path = Path(q.cropped_image_path)
                        full_cand = cand_path if cand_path.is_absolute() else (settings.BASE_DIR / cand_path)
                        # Only use if it lives under the same cropped_dir (same exam, same algo version)
                        try:
                            full_cand.resolve().relative_to(cropped_dir.resolve())
                            same_dir = True
                        except ValueError:
                            same_dir = False
                        if same_dir and full_cand.exists() and full_cand.stat().st_size > 500:
                            target_img_path = full_cand
                        elif not same_dir:
                            logger.debug(
                                f"Skipping stale cropped_image_path for Q{q.index} "
                                f"(different dir: {full_cand} vs {cropped_dir})"
                            )

                    # 3rd priority: re-crop on the fly
                    if not target_img_path:
                        crop_res = crop_question_single(
                            input_path=full_raw_path,
                            output_path=cropped_path,
                        )
                        target_img_path = cropped_path

                    target_img = Image.open(target_img_path)

                # Ensure image passed to python-docx is strictly PNG (python-docx lacks WebP support)
                if str(target_img_path).lower().endswith(".webp"):
                    converted_png = cropped_dir / f"q{q.index:03d}_converted.png"
                    target_img.save(converted_png, format="PNG")
                    target_img_path = converted_png

                # Scale image at 120 dpi (max 16.51 cm width)
                img_w_px = target_img.width
                width_cm = min(16.51, (img_w_px / 120.0) * 2.54)

                # Insert cropped PNG (or raw image fallback)
                img_paragraph.add_run().add_picture(str(target_img_path), width=Cm(width_cm))
                img_inserted = True
            except Exception as img_err:
                logger.warning(
                    f"Error cropping/inserting image for Q{q.index} ({full_raw_path}): "
                    f"{type(img_err).__name__}: {repr(img_err)}",
                    exc_info=True,
                )

    if not img_inserted:
        run_missing = img_paragraph.add_run(f"[Ảnh câu {q.index}]")
        run_missing.font.size = Pt(11)
        run_missing.font.italic = True
        run_missing.font.color.rgb = RGBColor(0x8C, 0x82, 0x78)

    # Note if source screenshot was clipped (only when content is lost: right/top/bottom, or explicit source_clipped_content)
    warnings_list = getattr(q, "crop_warnings", []) or []
    # If warnings list has "source_clipped_content" (or "source_clipped" when NOT general left-margin only)
    has_content_clipping = "source_clipped_content" in warnings_list or (
        "source_clipped" in warnings_list and "source_clipped_left_only" not in warnings_list
    )
    if has_content_clipping:
        note_p = doc.add_paragraph()
        note_p.paragraph_format.space_before = Pt(0)
        note_p.paragraph_format.space_after = Pt(2)
        note_p.paragraph_format.keep_with_next = True
        note_run = note_p.add_run("(ảnh nguồn bị cụt)")
        note_run.italic = True
        note_run.font.size = Pt(10)
        note_run.font.color.rgb = RGBColor(0x8C, 0x82, 0x78)

    # B. Answer Paragraph
    # Format: Bold 20pt Red #EE0000
    ans_paragraph = doc.add_paragraph()
    ans_paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    ans_paragraph.paragraph_format.space_before = Pt(0)
    ans_paragraph.paragraph_format.space_after = Pt(4 if add_divider else 16)
    ans_paragraph.paragraph_format.keep_together = True

    # Determine answer text and status
    ans_obj: Optional[Answer] = None
    if answers_map and q.id in answers_map:
        ans_obj = answers_map[q.id]
    else:
        try:
            if "answer" in q.__dict__:
                ans_obj = q.__dict__["answer"]
            else:
                ans_obj = getattr(q, "answer", None)
        except Exception as e:
            logger.warning(f"Could not load answer for Q{q.index} ({type(e).__name__}): {e}")
            ans_obj = None

    ans_text = "?"
    status = AnswerStatus.NO_DATA

    options_map = {}
    if ans_obj and ans_obj.vote_breakdown and isinstance(ans_obj.vote_breakdown, dict):
        options_map = ans_obj.vote_breakdown.get("_options", {})

    if ans_obj and ans_obj.answer_set:
        import json
        raw_ans_set = ans_obj.answer_set
        if isinstance(raw_ans_set, str):
            try:
                ans_list = json.loads(raw_ans_set)
                if not isinstance(ans_list, list):
                    ans_list = [raw_ans_set]
            except Exception:
                ans_list = [raw_ans_set]
        elif isinstance(raw_ans_set, (list, tuple, set)):
            ans_list = list(raw_ans_set)
        else:
            ans_list = [str(raw_ans_set)]

        is_vi = (
            subject_code.upper() in ["MLN122", "VIE101", "HCM202", "VNR202"]
            or any(c in exam_title.lower() for c in "àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ")
        )

        if len(ans_list) > 1:
            # Multi-choice question: ONLY write letters, NEVER output keywords!
            if multi_choice_format == "joined":
                ans_text = "".join(str(l).strip().upper() for l in ans_list)
            else:
                ans_text = ", ".join(str(l).strip().upper() for l in ans_list)
        else:
            # Single-choice question
            clean_letter = str(ans_list[0]).strip().upper() if ans_list else "?"
            kw = options_map.get(clean_letter) if (answer_format == "letter_keyword" and options_map) else None
            if kw and is_valid_keyword(kw, is_vietnamese_exam=is_vi):
                ans_text = f"{clean_letter}. {kw.strip()}"
            else:
                ans_text = clean_letter
        status = ans_obj.status
    elif ans_obj and ans_obj.status:
        status = ans_obj.status

    # Missing options in source image check: cluster text comments if available
    raw_warnings = getattr(q, "crop_warnings", []) or []
    if isinstance(raw_warnings, str):
        try:
            import json
            raw_warnings = json.loads(raw_warnings)
        except Exception:
            raw_warnings = [raw_warnings]

    # Detect if options are missing either from crop warnings or if comments are predominantly text descriptions
    has_missing_options = "missing_options" in raw_warnings
    q_comms = getattr(q, "__dict__", {}).get("comments") or []
    if not isinstance(q_comms, list):
        q_comms = []
    if not has_missing_options and ("few_lines" in raw_warnings or "crop_too_small" in raw_warnings or "missing_stem" in raw_warnings) and q_comms and len(q_comms) >= 1:
        # Check if majority of comments are textual descriptive phrases rather than isolated letters
        from backend.app.modules.analysis.parser import parse_comment_text
        phrase_cnt = 0
        letter_cnt = 0
        for c_item in q_comms:
            txt = getattr(c_item, "raw_text", "") or ""
            lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
            time_idx = -1
            for i_ln, ln in enumerate(lines):
                if re.search(r"(?:lúc\s+\d{1,2}:\d{2}|\b\d{1,2}\/\d{1,2}\/\d{2,4}\b)", ln, re.IGNORECASE):
                    time_idx = i_ln
                    break
            if time_idx != -1:
                txt = " ".join(lines[time_idx + 1:]).strip()
            if not txt:
                continue

            parsed = parse_comment_text(txt)
            if parsed and parsed.answers and any(a in ["A", "B", "C", "D"] for a in parsed.answers):
                # If comment has letter but also substantial descriptive text (e.g. 'B. Tuyệt đối của chủ nghĩa tư bản')
                cleaned = re.sub(r"^[A-Da-d][.\s:\-]+", "", txt.strip())
                if len(cleaned.split()) >= 3:
                    phrase_cnt += 1
                else:
                    letter_cnt += 1
            elif len(txt.strip().split()) >= 3:
                phrase_cnt += 1

        if phrase_cnt > 0 and phrase_cnt >= letter_cnt and (status in (AnswerStatus.WEAK, AnswerStatus.NO_DATA) or not ans_obj or not ans_obj.answer_set):
            has_missing_options = True

    if has_missing_options:
        text_answer = cluster_text_answers(q_comms)
        if text_answer:
            ans_text = f"{text_answer} (ảnh nguồn thiếu phương án)"
        else:
            ans_text = f"{ans_text} (ảnh nguồn thiếu phương án)"

    # Quality gate on answer string: no newlines/tabs, no timestamp, max 120 chars
    if any(c in ans_text for c in ['\n', '\r', '\t']):
        raise ValueError(f"Quality gate error: answer contains newline/tab: {repr(ans_text)}")
    if re.search(r"lúc\s+\d{1,2}:\d{2}", ans_text, re.IGNORECASE):
        raise ValueError(f"Quality gate error: answer contains timestamp string: {repr(ans_text)}")
    if len(ans_text) > 120:
        raise ValueError(f"Quality gate error: answer length exceeds 120 chars ({len(ans_text)} chars): {repr(ans_text[:50])}...")

    # Answer letter run
    run_ans = ans_paragraph.add_run(ans_text)
    run_ans.bold = True
    run_ans.font.size = Pt(20)
    run_ans.font.color.rgb = RGBColor(0xEE, 0x00, 0x00)  # Teacher Red #EE0000

    # 1. Cờ phiếu (Vote consensus / uncertainty)
    # BỎ hậu tố "(cần kiểm tra lại)" theo Requirement 2. Cảnh báo độ tin cậy chuyển vào .meta.json.

    # 2. Cờ ảnh (Crop / image quality warnings on this specific question only)
    image_note = ""
    if has_content_clipping or "source_clipped_content" in raw_warnings:
        image_note = " (ảnh có thể thiếu)"
    elif has_missing_options or "missing_options" in raw_warnings:
        image_note = " (ảnh thiếu phương án)"
    elif "crop_too_large" in raw_warnings:
        image_note = " (ảnh chưa cắt gọn)"
    elif "no_text" in raw_warnings:
        image_note = " (ảnh không có chữ)"

    if image_note:
        run_img_note = ans_paragraph.add_run(image_note)
        run_img_note.bold = False
        run_img_note.font.size = Pt(11)
        run_img_note.font.color.rgb = RGBColor(0x7F, 0x7F, 0x7F)  # Muted grey 11pt

    # C. Horizontal Divider (Double Border '===')
    if add_divider:
        div_paragraph = doc.add_paragraph()
        div_paragraph.paragraph_format.space_before = Pt(2)
        div_paragraph.paragraph_format.space_after = Pt(14)
        pBdr = parse_xml(
            f'<w:pBdr {nsdecls("w")}><w:bottom w:val="double" w:sz="12" w:space="4" w:color="auto"/></w:pBdr>'
        )
        div_paragraph._p.get_or_add_pPr().append(pBdr)

    return ans_text


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
    multi_choice_format: str = "comma",
    add_divider: bool = True,
    add_question_number: bool = True,
    unsupported_layout_warning: bool = False,
    use_raw_fallback: bool = False,
    answers_map: Optional[Dict[int, Answer]] = None,
    platform: Optional[str] = None,
    sub_exam_code: Optional[str] = None,
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
      - Answer line contains ONLY letter / letter + keyword (NO '(cần kiểm tra lại)' in Word).
      - Confidence breakdown & review list stored in .meta.json.
    """
    exam_title_clean = exam.title.strip()
    if exam_title_clean.upper().startswith(f"{subject_code.upper()} -"):
        display_title = exam_title_clean
    else:
        display_title = f"{subject_code} - {exam_title_clean}"
    logger.info(f"Building Word document for {display_title} ({len(questions)} questions)...")

    if output_dir is None:
        plat_tag = "FUE" if (platform and "fuexam" in platform.lower()) else "FUO"
        output_dir = settings.STORAGE_DIR / "output" / plat_tag / subject_code.upper().strip()
    output_dir.mkdir(parents=True, exist_ok=True)

    if cropped_dir is None:
        cropped_dir = settings.STORAGE_DIR / "cropped" / subject_code / f"exam_{exam.id}"
    cropped_dir.mkdir(parents=True, exist_ok=True)

    doc = Document()
    _setup_letter_margins(doc)

    if unsupported_layout_warning:
        warn_p = doc.add_paragraph()
        warn_p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        warn_run = warn_p.add_run(
            "[LƯU Ý: Bố cục hình ảnh của đề thi này chưa được hệ thống hỗ trợ cắt tự động (>20% cảnh báo). "
            "Tài liệu đang được xuất bằng ảnh gốc để đảm bảo trọn vẹn nội dung câu hỏi.]"
        )
        warn_run.bold = True
        warn_run.font.size = Pt(11)
        warn_run.font.color.rgb = RGBColor(0xDC, 0x26, 0x26)
        warn_p.paragraph_format.space_after = Pt(12)

    # Check if this exam has widespread left-edge clipping (ONLY if questions have actual content loss touching screenshot canvas)
    has_exam_left_clipped = False
    for q in questions:
        q_warns = getattr(q, "crop_warnings", []) or []
        # Only display exam-wide note if source screenshot canvas was genuinely clipped
        if "source_clipped_content" in q_warns:
            has_exam_left_clipped = True
            break
    if has_exam_left_clipped:
        left_clip_p = doc.add_paragraph()
        left_clip_p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        left_clip_run = left_clip_p.add_run("Ảnh nguồn của đề này bị cụt mép trái")
        left_clip_run.italic = True
        left_clip_run.font.size = Pt(10.5)
        left_clip_run.font.color.rgb = RGBColor(0x8C, 0x82, 0x78)
        left_clip_p.paragraph_format.space_after = Pt(8)

    sorted_questions = sorted(questions, key=lambda q: q.index)
    rendered_q_mark_count = 0
    available_db_answers_count = 0
    rendered_answers_map: Dict[int, str] = {}

    for q in sorted_questions:
        ans_in_db = answers_map.get(q.id) if answers_map else getattr(q, "answer", None)
        if ans_in_db and ans_in_db.answer_set and ans_in_db.status != AnswerStatus.NO_DATA:
            available_db_answers_count += 1

        ans_rendered = _render_question_to_doc(
            doc=doc,
            q=q,
            cropped_dir=cropped_dir,
            highlight_check_needed=highlight_check_needed,
            answer_format=answer_format,
            multi_choice_format=multi_choice_format,
            add_divider=add_divider,
            add_question_number=add_question_number,
            use_raw_fallback=use_raw_fallback,
            answers_map=answers_map,
            subject_code=subject_code,
            exam_title=exam.title,
        )
        rendered_answers_map[q.id] = ans_rendered
        if ans_rendered == "?" and ans_in_db and ans_in_db.answer_set and ans_in_db.status != AnswerStatus.NO_DATA:
            rendered_q_mark_count += 1

    # Quality Gate Check: fail job if >= 50% of questions render as '?' when DB has answers
    if available_db_answers_count > 0:
        q_mark_ratio = rendered_q_mark_count / available_db_answers_count
        if q_mark_ratio >= 0.50:
            err_msg = (
                f"Lỗi kiểm tra chất lượng file Word: {rendered_q_mark_count}/{available_db_answers_count} câu "
                f"bị hiển thị '?' dù cơ sở dữ liệu đã có sẵn đáp án (tỷ lệ {q_mark_ratio * 100:.1f}% >= 50%). "
                "Đã chặn xuất file để ngăn ngừa lỗi dữ liệu rỗng."
            )
            logger.error(err_msg)
            raise RuntimeError(err_msg)

    filename = format_exam_docx_filename(subject_code, exam, platform=platform, sub_exam_code=sub_exam_code)
    file_path = output_dir / filename

    # Overwrite Protection: Check if target file already exists and belongs to a different thread
    if file_path.exists():
        meta_file = output_dir / f"{filename}.meta.json"
        if meta_file.exists():
            try:
                old_meta = json.loads(meta_file.read_text(encoding="utf-8"))
                old_tid = old_meta.get("thread_id")
                curr_tid = getattr(exam, "id", None)
                if old_tid is not None and curr_tid is not None and str(old_tid) != str(curr_tid):
                    err_msg = (
                        f"Phát hiện xung đột ghi đè: File '{filename}' đã tồn tại và thuộc về Thread {old_tid} "
                        f"(nguồn: {old_meta.get('source_url', 'N/A')}), khác với Thread {curr_tid} hiện tại. "
                        f"Hệ thống dừng biên soạn để tránh ghi đè dữ liệu giữa các thread khác nhau."
                    )
                    logger.error(err_msg)
                    raise RuntimeError(err_msg)
            except (json.JSONDecodeError, OSError):
                pass

    temp_file_path = output_dir / f"{filename}.tmp_{os.getpid()}_{int(time.time())}.docx"

    # Save initially to a temporary file
    doc.save(str(temp_file_path))
    temp_size = temp_file_path.stat().st_size

    # Quality Gate Check 1: Abnormally small file when questions > 5
    if len(questions) > 5 and temp_size < 50_000:
        err_msg = (
            f"Lỗi cổng chất lượng file Word: Kích thước file tạo ra quá nhỏ bất thường ({temp_size} bytes "
            f"cho {len(questions)} câu). Đã chặn ghi đè tài liệu thật."
        )
        if temp_file_path.exists():
            temp_file_path.unlink()
        logger.error(err_msg)
        raise RuntimeError(err_msg)

    # Quality Gate Check 2: Reject overwriting a healthy file (>1MB) with an abnormally small file (<100KB)
    if file_path.exists():
        existing_size = file_path.stat().st_size
        if existing_size > 1_000_000 and temp_size < 100_000:
            err_msg = (
                f"Lỗi cổng chất lượng: Từ chối ghi đè file Word hiện tại ({existing_size} bytes) "
                f"bằng file mới nhỏ bất thường ({temp_size} bytes)."
            )
            if temp_file_path.exists():
                temp_file_path.unlink()
            logger.error(err_msg)
            raise RuntimeError(err_msg)

    # Atomic replace
    os.replace(str(temp_file_path), str(file_path))

    # Save sidecar metadata .meta.json (Requirement 2 & Requirement 3 & Requirement 4)
    meta_file = output_dir / f"{filename}.meta.json"
    confident_cnt = 0
    weak_cnt = 0
    conflict_cnt = 0
    ai_cnt = 0
    image_cnt = 0
    comment_cnt = 0
    no_data_cnt = 0
    review_needed_qs: List[int] = []

    for q in sorted_questions:
        ans = answers_map.get(q.id) if answers_map else getattr(q, "answer", None)
        ans_text = rendered_answers_map.get(q.id, "")
        is_q_mark = (ans_text == "?" or ans_text.startswith("?"))
        st = (ans.status.value if hasattr(ans.status, "value") else str(getattr(ans, "status", "") or "")).upper() if ans else ""
        src = ans.vote_breakdown.get("_source", "") if (ans and ans.vote_breakdown and isinstance(ans.vote_breakdown, dict)) else ""
        is_ai = getattr(ans, "source", None) == "ai" or src == "ai" or st == "AI"

        if not ans or is_q_mark or st == "NO_DATA" or src == "no_data":
            no_data_cnt += 1
            review_needed_qs.append(q.index)
        elif is_ai:
            ai_cnt += 1
            review_needed_qs.append(q.index)
        elif st == "CONFLICT":
            conflict_cnt += 1
            review_needed_qs.append(q.index)
            if src == "image":
                image_cnt += 1
            else:
                comment_cnt += 1
        elif st == "WEAK":
            weak_cnt += 1
            review_needed_qs.append(q.index)
            if src == "image":
                image_cnt += 1
            else:
                comment_cnt += 1
        elif st == "CONFIDENT":
            confident_cnt += 1
            if src == "image":
                image_cnt += 1
            else:
                comment_cnt += 1
        else:
            no_data_cnt += 1
            review_needed_qs.append(q.index)

    sidecar_meta = {
        "filename": filename,
        "subject_code": subject_code.upper().strip(),
        "exam_title": exam.title,
        "thread_id": getattr(exam, "id", None),
        "source_url": getattr(exam, "url", None),
        "platform": platform or ("fuexam" if "FUE" in filename else "fuoverflow"),
        "questions_count": len(questions),
        "confident_count": confident_cnt,
        "weak_count": weak_cnt,
        "conflict_count": conflict_cnt,
        "ai_count": ai_cnt,
        "image_count": image_cnt,
        "comment_count": comment_cnt,
        "no_data_count": no_data_cnt,
        "source_breakdown": {
            "image": image_cnt,
            "comments": comment_cnt,
            "ai": ai_cnt,
            "no_data": no_data_cnt,
        },
        "review_needed_questions": sorted(list(set(review_needed_qs))),
        "updated_at": datetime.now().isoformat(),
    }
    meta_file.write_text(json.dumps(sidecar_meta, indent=2, ensure_ascii=False), encoding="utf-8")

    logger.info(f"Generated clean Word document: {file_path} (Size: {file_path.stat().st_size} bytes)")
    return file_path


def build_merged_docx(
    subject_code: str,
    exams_data: list,
    output_dir: Optional[Path] = None,
    highlight_check_needed: bool = True,
    answer_format: str = "letter_keyword",
    multi_choice_format: str = "comma",
    add_divider: bool = True,
    add_question_number: bool = True,
    answers_map: Optional[Dict[int, Answer]] = None,
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

    merged_q_mark_count = 0
    merged_db_ans_count = 0

    for i, (exam, questions) in enumerate(exams_data):
        if i > 0:
            doc.add_page_break()

        cropped_dir = settings.STORAGE_DIR / "cropped" / code / f"exam_{exam.id}"
        cropped_dir.mkdir(parents=True, exist_ok=True)

        sorted_questions = sorted(questions, key=lambda q: q.index)
        for q in sorted_questions:
            ans_in_db = answers_map.get(q.id) if answers_map else getattr(q, "answer", None)
            if ans_in_db and ans_in_db.answer_set and ans_in_db.status != AnswerStatus.NO_DATA:
                merged_db_ans_count += 1

            ans_rendered = _render_question_to_doc(
                doc=doc,
                q=q,
                cropped_dir=cropped_dir,
                highlight_check_needed=highlight_check_needed,
                answer_format=answer_format,
                multi_choice_format=multi_choice_format,
                add_divider=add_divider,
                add_question_number=add_question_number,
                answers_map=answers_map,
                subject_code=code,
                exam_title=exam.title,
            )
            if ans_rendered == "?" and ans_in_db and ans_in_db.answer_set and ans_in_db.status != AnswerStatus.NO_DATA:
                merged_q_mark_count += 1

    if merged_db_ans_count > 0:
        q_mark_ratio = merged_q_mark_count / merged_db_ans_count
        if q_mark_ratio >= 0.50:
            err_msg = (
                f"Lỗi kiểm tra chất lượng file Word gộp: {merged_q_mark_count}/{merged_db_ans_count} câu "
                f"bị hiển thị '?' dù cơ sở dữ liệu đã có sẵn đáp án (tỷ lệ {q_mark_ratio * 100:.1f}% >= 50%). "
                "Đã chặn xuất file gộp."
            )
            logger.error(err_msg)
            raise RuntimeError(err_msg)

    filename = f"{code} - Merged - FE.docx"
    file_path = output_dir / filename
    doc.save(str(file_path))

    logger.info(f"Generated merged Word document: {file_path} (Size: {file_path.stat().st_size} bytes)")
    return file_path
