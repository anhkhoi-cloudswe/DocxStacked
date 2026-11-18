import sys
from pathlib import Path
repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root))

import hashlib
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from docx import Document

from backend.app.db.models import Exam, Question
from backend.app.modules.export.image_cropper import crop_exam_images
from backend.app.modules.export.docx_builder import build_exam_docx

def main():
    db_path = repo_root / "data" / "docxstacked.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Session = sessionmaker(bind=engine)
    session = Session()

    exam_id = 192
    exam = session.query(Exam).filter(Exam.id == exam_id).first()
    if not exam:
        print(f"Exam {exam_id} not found!")
        return

    subject_code = "PRN232"
    questions = session.query(Question).filter(Question.exam_id == exam_id).order_by(Question.index).all()
    print(f"Exam {exam.id}: {exam.title} ({len(questions)} questions)")

    # Directories
    raw_dir = repo_root / "data" / "storage" / "raw" / subject_code / "exam_192_su26"
    cropped_dir = repo_root / "data" / "storage" / "cropped" / subject_code / "exam_192_su26"
    output_dir = repo_root / "data" / "storage" / "output" / subject_code

    # Step 1: Crop images
    print("\n--- Running crop_exam_images ---")
    crop_summary = crop_exam_images(
        exam_id=exam.id,
        exam_title=exam.title,
        questions=questions,
        cropped_dir=cropped_dir,
    )
    print(f"Crop layout: {crop_summary.dominant_layout}")
    print(f"Clean crops: {crop_summary.clean_questions}/{crop_summary.total_questions}")
    print(f"Flagged questions: {crop_summary.flagged_questions}")
    for idx, res in enumerate(crop_summary.results, 1):
        if res.warnings:
            print(f"  Question Q{idx} has warnings: {res.warnings}")

    # Step 2: Build docx
    print("\n--- Running build_exam_docx ---")
    output_docx = build_exam_docx(
        subject_code=subject_code,
        exam=exam,
        questions=questions,
        output_dir=output_dir,
        cropped_dir=cropped_dir,
    )

    data = output_docx.read_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    size = len(data)

    print(f"\nGenerated docx: {output_docx}")
    print(f"File size: {size} bytes")
    print(f"SHA256: {sha256}")

    # Inspect docx paragraphs
    doc = Document(str(output_docx))
    cur_q = None
    flagged = []
    for p in doc.paragraphs:
        text = p.text.strip()
        if text.startswith("Câu ") and ":" in text:
            cur_q = text.split(":")[0].strip()
        if text.startswith("Đáp án:"):
            if "cần kiểm tra lại" in text:
                flagged.append((cur_q, text))
            if cur_q == "Câu 43":
                print(f"\n-> Q43 exact in docx: '{text}'")

    print(f"\nTotal flagged questions in Word doc: {len(flagged)}")
    for q, t in flagged:
        print(f"  {q}: {t}")

if __name__ == "__main__":
    main()
