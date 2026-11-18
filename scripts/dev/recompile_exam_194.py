import sys
import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Setup paths
repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root))

from backend.app.db.models import Exam, Question, ExamStatus, AnswerStatus
from backend.app.modules.export.image_cropper import crop_exam_images
from backend.app.modules.export.docx_builder import build_exam_docx

def main():
    db_path = repo_root / "data" / "docxstacked.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Session = sessionmaker(bind=engine)
    session = Session()

    exam = session.query(Exam).filter(Exam.id == 194).first()
    if not exam:
        print("Exam 194 not found!")
        return

    subject_code = exam.subject.code
    print(f"Exam ID: {exam.id}")
    print(f"Title: {exam.title}")
    print(f"Subject: {subject_code}")
    print(f"Status: {exam.status}")

    questions = session.query(Question).filter(Question.exam_id == 194).order_by(Question.index).all()
    print(f"Total questions in DB: {len(questions)}")

    q_dicts = []
    for q in questions:
        ans_obj = q.answer
        ans_str = "/".join(ans_obj.answer_set) if (ans_obj and ans_obj.answer_set) else ""
        img_p = str(repo_root / q.local_image_path) if q.local_image_path else ""
        q_dicts.append({
            "index": q.index,
            "image_path": img_p,
            "correct_answer": ans_str,
            "explanation": ans_obj.explanation if ans_obj else "",
            "has_explanation": bool(ans_obj and ans_obj.explanation),
            "flagged": False,
            "flag_reason": "",
            "ai_confidence": ans_obj.confidence if ans_obj else 0.0,
            "crop_box": None,
            "options": [],
            "comments": []
        })

    cropped_dir = repo_root / "data" / "cropped" / subject_code / f"exam_{exam.id}"
    output_dir = repo_root / "data" / "output" / subject_code

    # Step 1: Crop exam images using current algorithm
    print("\n--- Running crop_exam_images ---")
    crop_summary = crop_exam_images(
        exam_id=exam.id,
        exam_title=exam.title,
        questions=questions,
        cropped_dir=cropped_dir
    )
    print(f"Dominant layout: {crop_summary.dominant_layout}")
    print(f"Total questions: {crop_summary.total_questions}")
    print(f"Clean questions: {crop_summary.clean_questions}")
    print(f"Flagged questions: {crop_summary.flagged_questions}")
    print(f"Warning rate: {crop_summary.warning_rate:.1%}")
    print(f"Fallback to raw: {crop_summary.fallback_to_raw}")

    # Step 2: Build docx
    print("\n--- Running build_exam_docx ---")
    output_docx = build_exam_docx(
        subject_code=subject_code,
        exam=exam,
        questions=questions,
        output_dir=output_dir,
        cropped_dir=cropped_dir,
        unsupported_layout_warning=crop_summary.fallback_to_raw,
        use_raw_fallback=crop_summary.fallback_to_raw,
    )

    docx_path = Path(output_docx)
    print(f"\nGenerated docx path: {docx_path}")
    print(f"File exists: {docx_path.exists()}")
    file_size = docx_path.stat().st_size
    print(f"File size: {file_size} bytes ({file_size / 1024:.2f} KB)")

    # Update exam and questions in DB
    exam.status = ExamStatus.CRAWLED
    exam.crop_layout = crop_summary.dominant_layout
    
    flagged_count = 0
    print("\n--- 50 ANSWERS & FLAGS ---")
    for q_obj, crop_res in zip(questions, crop_summary.results):
        q_obj.crop_layout = crop_res.layout
        q_obj.crop_warnings = crop_res.warnings
        q_obj.cropped_image_path = str(crop_res.output_path) if crop_res.output_path else None
        
        ans_obj = q_obj.answer
        ans = "/".join(ans_obj.answer_set) if (ans_obj and ans_obj.answer_set) else "?"
        is_check_needed = (ans_obj is None or ans_obj.status in [AnswerStatus.WEAK, AnswerStatus.CONFLICT, AnswerStatus.NO_DATA])
        if is_check_needed:
            flagged_count += 1
        print(f"Q{q_obj.index:02d}: Answer={ans} | Check needed={is_check_needed} (status={ans_obj.status.value if ans_obj else 'no_data'}, warnings={crop_res.warnings})")

    session.commit()
    print(f"\nTotal questions with 'cần kiểm tra lại': {flagged_count}/50")
    print(f"Final status: CRAWLED")

    session.close()

if __name__ == "__main__":
    main()
