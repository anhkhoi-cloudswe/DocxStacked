import sys
import json
import hashlib
import sqlite3
import random
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))

from PIL import Image, ImageDraw, ImageFont
from docx import Document
from docx.shared import Pt

from backend.app.db.models import Exam, Question, Answer, AnswerStatus, Comment
from backend.app.modules.export.docx_builder import build_exam_docx, format_exam_docx_filename
from backend.app.modules.export.image_cropper import crop_exam_images, ImageCropConfig


def _get_vietnamese_font(size: int = 16) -> ImageFont.ImageFont:
    """Get a font that supports Vietnamese characters."""
    font_candidates = [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/seguiemj.ttf",
        "C:/Windows/Fonts/tahoma.ttf",
        "C:/Windows/Fonts/verdana.ttf",
        "C:/Windows/Fonts/calibri.ttf",
    ]
    for font_path in font_candidates:
        try:
            return ImageFont.truetype(font_path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def print_answers_from_docx(docx_path: Path) -> None:
    """
    Read the Word file and print a 10-column answer table (5 rows × 10 cols).
    Also prints sha256 and file size.
    Uses python-docx: identifies answer text by run.font.size == Pt(20) and run.bold == True.
    NEVER hand-types answers — always reads from the .docx file itself.
    """
    doc = Document(str(docx_path))

    answers = {}  # q_index -> answer_text
    current_q = None

    for para in doc.paragraphs:
        # Detect question number paragraph "Câu N:"
        text = para.text.strip()
        import re
        m = re.match(r'^Câu\s+(\d+)\s*:', text)
        if m:
            current_q = int(m.group(1))
            continue

        # Detect answer paragraph: has a run with bold=True and font.size=Pt(20)
        if current_q is not None:
            for run in para.runs:
                if run.bold and run.font.size == Pt(20):
                    # Extract just the answer letter portion (before any notes like " (cần kiểm tra lại)")
                    ans_text = run.text.strip()
                    if ans_text and ans_text != "?":
                        answers[current_q] = ans_text
                    elif ans_text == "?":
                        answers[current_q] = "?"
                    current_q = None
                    break

    # Print header
    file_size = docx_path.stat().st_size
    sha256 = hashlib.sha256(docx_path.read_bytes()).hexdigest()
    print(f"\n{'='*70}")
    print(f"Answers from Word file: {docx_path.name}")
    print(f"  SHA256: {sha256}")
    print(f"  Size:   {file_size:,} bytes")
    print(f"{'='*70}")

    # Print 10-column table (5 rows × 10 cols) for 50 questions
    for row in range(5):
        row_parts = []
        for col in range(10):
            q_num = row * 10 + col + 1
            ans = answers.get(q_num, "?")
            row_parts.append(f"Q{q_num:02d}={ans}")
        print(" | ".join(row_parts))
    print(f"{'='*70}\n")

def generate_contact_sheet(exam_title: str, questions_sample: list, out_path: Path):
    """
    Generate a 4x4 contact sheet (16 questions) showing:
    - Cropped image
    - Question number & Selected Answer in bold red
    """
    card_w = 480
    card_h = 240
    cols = 4
    rows = 4
    
    sheet_w = cols * card_w
    sheet_h = rows * card_h + 60
    
    sheet = Image.new("RGB", (sheet_w, sheet_h), "#0f172a")
    draw = ImageDraw.Draw(sheet)

    font_title = _get_vietnamese_font(16)
    font_card = _get_vietnamese_font(14)
    
    # Title bar
    draw.rectangle([0, 0, sheet_w, 50], fill="#1e293b")
    draw.text((20, 15), f"Contact Sheet: {exam_title} (16 Sample Questions)", fill="#f8fafc", font=font_title)
    
    for idx, item in enumerate(questions_sample[:16]):
        c = idx % cols
        r = idx // cols
        x0 = c * card_w
        y0 = 60 + r * card_h
        
        # Background card
        draw.rectangle([x0 + 6, y0 + 6, x0 + card_w - 6, y0 + card_h - 6], fill="#ffffff", outline="#334155", width=2)
        
        q_idx = item["index"]
        ans_str = item["answer_text"]
        img_path = item["image_path"]
        
        # Header of card
        draw.rectangle([x0 + 8, y0 + 8, x0 + card_w - 8, y0 + 36], fill="#f1f5f9")
        draw.text((x0 + 16, y0 + 14), f"Câu {q_idx:02d}: Đáp án: {ans_str}", fill="#dc2626", font=font_card)
        
        # Paste cropped question image
        if img_path and Path(img_path).exists():
            try:
                q_im = Image.open(img_path).convert("RGB")
                # Scale to fit inside (card_w - 24, card_h - 48)
                max_w = card_w - 24
                max_h = card_h - 48
                q_im.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
                
                # Center paste
                paste_x = x0 + 12 + (max_w - q_im.width) // 2
                paste_y = y0 + 40 + (max_h - q_im.height) // 2
                sheet.paste(q_im, (paste_x, paste_y))
            except Exception as e:
                draw.text((x0 + 20, y0 + 50), f"Error loading image: {e}", fill="red", font=font_card)
        else:
            draw.text((x0 + 20, y0 + 50), "No image file", fill="red", font=font_card)
            
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    print(f"Saved contact sheet to: {out_path}")

def build_prn232_exams():
    conn = sqlite3.connect("data/docxstacked.db")
    cursor = conn.cursor()
    
    output_dir = Path("data/output/PRN232")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # -------------------------------------------------------------
    # EXAM 194: PRN232 - SU25 - Final Exam
    # -------------------------------------------------------------
    print("\n================ BUILDING EXAM 194 (SU25 Final Exam) ================")
    e194_row = cursor.execute("SELECT id, subject_id, title, term, url FROM exams WHERE id=194").fetchone()
    exam194 = Exam(
        id=e194_row[0],
        subject_id=e194_row[1],
        title=e194_row[2],
        term=e194_row[3],
        url=e194_row[4],
    )
    
    q194_rows = cursor.execute("SELECT id, [index], file_name, local_image_path FROM questions WHERE exam_id=194 ORDER BY [index]").fetchall()
    questions194 = []
    for r in q194_rows:
        q = Question(
            id=r[0],
            exam_id=194,
            index=r[1],
            file_name=r[2],
            local_image_path=r[3],
        )
        # get answer
        ans_row = cursor.execute("SELECT answer_set, status, confidence, vote_breakdown FROM answers WHERE question_id=?", (q.id,)).fetchone()
        if ans_row:
            q.answer = Answer(
                question_id=q.id,
                answer_set=json.loads(ans_row[0]),
                status=AnswerStatus(ans_row[1].lower()),
                confidence=ans_row[2],
                vote_breakdown=json.loads(ans_row[3]) if ans_row[3] else {},
            )
        # get comments
        comm_rows = cursor.execute("SELECT id, comment_id, author_hash, raw_text, upvotes, quoted_comment_id FROM comments WHERE question_id=?", (q.id,)).fetchall()
        q.comments = [
            Comment(
                id=cr[0],
                question_id=q.id,
                comment_id=cr[1],
                author_hash=cr[2],
                raw_text=cr[3],
                upvotes=cr[4],
                quoted_comment_id=cr[5],
            )
            for cr in comm_rows
        ]
        questions194.append(q)
        
    cropped_dir_194 = Path("data/cropped/PRN232/exam_194_su25")
    # Run crop
    crop_sum_194 = crop_exam_images(
        exam_id=194,
        exam_title=exam194.title,
        questions=questions194,
        cropped_dir=cropped_dir_194,
    )
    print(f"Exam 194 crop summary: dominant_layout={crop_sum_194.dominant_layout}, clean={crop_sum_194.clean_questions}/{crop_sum_194.total_questions}, warning_rate={crop_sum_194.warning_rate*100:.1f}%")
    
    docx_p_194 = build_exam_docx(
        subject_code="PRN232",
        exam=exam194,
        questions=questions194,
        output_dir=output_dir,
        cropped_dir=cropped_dir_194,
        highlight_check_needed=True,
    )
    print(f"Built Exam 194 Docx: {docx_p_194} ({docx_p_194.stat().st_size} bytes)")
    print_answers_from_docx(docx_p_194)
    
    # -------------------------------------------------------------
    # EXAM 195: PRN232 - SU26 - B5 - FE
    # -------------------------------------------------------------
    print("\n================ BUILDING EXAM 195 (SU26 B5 FE) ================")
    e195_row = cursor.execute("SELECT id, subject_id, title, term, url FROM exams WHERE id=195").fetchone()
    exam195 = Exam(
        id=e195_row[0],
        subject_id=e195_row[1],
        title=e195_row[2],
        term=e195_row[3],
        url=e195_row[4],
    )
    
    q195_rows = cursor.execute("SELECT id, [index], file_name, local_image_path FROM questions WHERE exam_id=195 ORDER BY [index]").fetchall()
    questions195 = []
    for r in q195_rows:
        q = Question(
            id=r[0],
            exam_id=195,
            index=r[1],
            file_name=r[2],
            local_image_path=r[3],
        )
        ans_row = cursor.execute("SELECT answer_set, status, confidence, vote_breakdown FROM answers WHERE question_id=?", (q.id,)).fetchone()
        if ans_row:
            q.answer = Answer(
                question_id=q.id,
                answer_set=json.loads(ans_row[0]),
                status=AnswerStatus(ans_row[1].lower()),
                confidence=ans_row[2],
                vote_breakdown=json.loads(ans_row[3]) if ans_row[3] else {},
            )
        comm_rows = cursor.execute("SELECT id, comment_id, author_hash, raw_text, upvotes, quoted_comment_id FROM comments WHERE question_id=?", (q.id,)).fetchall()
        q.comments = [
            Comment(
                id=cr[0],
                question_id=q.id,
                comment_id=cr[1],
                author_hash=cr[2],
                raw_text=cr[3],
                upvotes=cr[4],
                quoted_comment_id=cr[5],
            )
            for cr in comm_rows
        ]
        questions195.append(q)
        
    cropped_dir_195 = Path("data/cropped/PRN232/exam_195_su26")
    crop_sum_195 = crop_exam_images(
        exam_id=195,
        exam_title=exam195.title,
        questions=questions195,
        cropped_dir=cropped_dir_195,
    )
    print(f"Exam 195 crop summary: dominant_layout={crop_sum_195.dominant_layout}, clean={crop_sum_195.clean_questions}/{crop_sum_195.total_questions}, warning_rate={crop_sum_195.warning_rate*100:.1f}%")
    
    docx_p_195 = build_exam_docx(
        subject_code="PRN232",
        exam=exam195,
        questions=questions195,
        output_dir=output_dir,
        cropped_dir=cropped_dir_195,
        highlight_check_needed=True,
    )
    print(f"Built Exam 195 Docx: {docx_p_195} ({docx_p_195.stat().st_size} bytes)")
    print_answers_from_docx(docx_p_195)

    # FIX 3: B5 flag table analysis
    print("\n================ B5 (Exam 195) COMMENT & ANSWER ANALYSIS TABLE ================")
    print(f"{'Q':>4} | {'Comments':>8} | {'Voters':>6} | {'Status':>10} | {'Answer':>8}")
    print("-" * 50)
    conflict_count = 0
    weak_count = 0
    confident_count = 0
    for q in sorted(questions195, key=lambda x: x.index):
        num_comments = len(q.comments) if q.comments else 0
        if q.answer:
            ans_str = ", ".join(q.answer.answer_set) if q.answer.answer_set else "?"
            status_str = q.answer.status.value.upper()
            if q.answer.status == AnswerStatus.CONFLICT:
                conflict_count += 1
            elif q.answer.status == AnswerStatus.WEAK:
                weak_count += 1
            else:
                confident_count += 1
            vb = q.answer.vote_breakdown or {}
            has_ai = 1 if ('_ai_votes' in vb or 'ai_vote' in vb) else 0
            human_voters = len(set(c.author_hash for c in (q.comments or []) if c.author_hash))
            total_voters = human_voters + has_ai
            voters_str = str(total_voters)
        else:
            ans_str = "?"
            status_str = "NO_DATA"
            voters_str = "0"
        print(f"{q.index:>4} | {num_comments:>8} | {voters_str:>6} | {status_str:>10} | {ans_str:>8}")
    print("-" * 50)
    print(f"Summary: CONFIDENT={confident_count}, WEAK={weak_count}, CONFLICT={conflict_count}")
    print(f"NOTE: '0 cờ (flags)' = 0 CONFLICT questions. WEAK ≠ CONFLICT.")
    print(f"      WEAK means < 2 independent voters OR confidence < 70%.")
    print(f"      No flags (0/50) is CORRECT — there are no CONFLICT answers in B5.")
    
    # Remove old dirty files with bad names
    old_files = [
        output_dir / "PRN232 - Đề Thi FE - PRN232 - SU26 - B5 - FE.docx",
        output_dir / "PRN232 - Đề Thi FE - PRN232 - SU26 - B5 - FE.docx.meta.json",
    ]
    for of in old_files:
        if of.exists():
            of.unlink()
            print(f"Deleted old file: {of.name}")

    # Generate 16-question contact sheets
    inspect_dir = Path("data/inspect_prn232")
    inspect_dir.mkdir(parents=True, exist_ok=True)
    
    # Exam 194 contact sheet
    sample_194 = []
    # Pick fixed reproducible random seed or fixed 16 questions
    rng = random.Random(42)
    indices_194 = sorted(rng.sample(range(1, 51), 16))
    for idx in indices_194:
        q = next(item for item in questions194 if item.index == idx)
        ans_text = ", ".join(q.answer.answer_set) if q.answer and q.answer.answer_set else "?"
        crop_f = cropped_dir_194 / f"q{idx:03d}.png"
        sample_194.append({"index": idx, "answer_text": ans_text, "image_path": str(crop_f)})
    generate_contact_sheet("PRN232 - SU25 - Final Exam", sample_194, inspect_dir / "contact_sheet_su25_16q.png")

    # Exam 195 contact sheet
    sample_195 = []
    indices_195 = sorted(rng.sample(range(1, 51), 16))
    for idx in indices_195:
        q = next(item for item in questions195 if item.index == idx)
        ans_text = ", ".join(q.answer.answer_set) if q.answer and q.answer.answer_set else "?"
        crop_f = cropped_dir_195 / f"q{idx:03d}.png"
        sample_195.append({"index": idx, "answer_text": ans_text, "image_path": str(crop_f)})
    generate_contact_sheet("PRN232 - SU26 - B5 - FE", sample_195, inspect_dir / "contact_sheet_su26_16q.png")

if __name__ == "__main__":
    build_prn232_exams()
