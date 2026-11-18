import sys
from pathlib import Path
repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root))

import hashlib
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from docx import Document

from backend.app.db.models import Exam, Question, Answer
from backend.app.modules.export.docx_builder import build_exam_docx
from backend.app.modules.export.image_cropper import crop_exam_images

def main():
    db_path = repo_root / "data" / "docxstacked.db"
    engine = create_engine(f"sqlite:///{db_path}")
    Session = sessionmaker(bind=engine)
    session = Session()

    exam = session.query(Exam).filter(Exam.title.like("%PRN232%SP26%FE%")).first()
    print(f"Exam {exam.id}: {exam.title}")

    questions = session.query(Question).filter(Question.exam_id == exam.id).order_by(Question.index).all()
    cropped_dir = repo_root / "data" / "cropped" / "PRN232" / f"exam_{exam.id}"
    output_dir = repo_root / "data" / "output" / "PRN232"

    crop_summary = crop_exam_images(exam.id, exam.title, questions, cropped_dir)

    answers_map = {}
    for q in questions:
        ans = session.query(Answer).filter(Answer.question_id == q.id).first()
        if ans:
            answers_map[q.id] = ans

    out_docx = build_exam_docx(
        subject_code="PRN232",
        exam=exam,
        questions=questions,
        output_dir=output_dir,
        cropped_dir=cropped_dir,
        answers_map=answers_map,
    )

    data = out_docx.read_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    size = len(data)

    print("Recompiled docx:", out_docx)
    print("Size:", size, "bytes")
    print("SHA256:", sha256)

    doc = Document(str(out_docx))
    cur_q = None
    answers = []
    for p in doc.paragraphs:
        t = p.text.strip()
        if t.startswith("Câu ") and ":" in t:
            cur_q = t.split(":")[0].strip()
        elif cur_q and (t.startswith("A") or t.startswith("B") or t.startswith("C") or t.startswith("D") or t.startswith("?")):
            answers.append((cur_q, t))
            if cur_q in ["Câu 11", "Câu 29"]:
                print(f"  {cur_q}: {repr(t)}")
            cur_q = None

    print(f"\nTotal extracted answers: {len(answers)}")
    print("Answer table (50 questions):")
    for idx in range(0, len(answers), 10):
        batch = answers[idx:idx+10]
        line = " | ".join(f"{q.replace('Câu ', 'Q')}: {a}" for q, a in batch)
        print(f"  {line}")

if __name__ == "__main__":
    main()
