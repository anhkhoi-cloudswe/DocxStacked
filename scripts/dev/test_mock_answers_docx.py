from docx import Document
from backend.app.db.models import Answer, AnswerStatus, Exam, ExamType, Question
from backend.app.modules.export.docx_builder import build_exam_docx
from pathlib import Path

# Create a test exam with mock answers for demonstration:
exam = Exam(id=999, subject_id=1, title="CSD202 - SU26 - FE", term="SU26", exam_type=ExamType.FE)
q1 = Question(id=1, exam_id=999, index=1, local_image_path="data/raw/CSD202/exam_1_SU26/q01_Q1.webp")
q1.answer = Answer(question_id=1, answer_set=["B"], confidence=0.88, status=AnswerStatus.CONFIDENT)

q2 = Question(id=2, exam_id=999, index=2, local_image_path="data/raw/CSD202/exam_1_SU26/q02_Q2.webp")
q2.answer = Answer(question_id=2, answer_set=["A"], confidence=0.60, status=AnswerStatus.WEAK)

q3 = Question(id=3, exam_id=999, index=3, local_image_path="data/raw/CSD202/exam_1_SU26/q03_Q3.webp")
q3.answer = Answer(question_id=3, answer_set=["A", "C"], confidence=0.92, status=AnswerStatus.CONFIDENT)

q4 = Question(id=4, exam_id=999, index=4, local_image_path="data/raw/CSD202/exam_1_SU26/q04_Q4.webp")
q4.answer = Answer(question_id=4, answer_set=["D"], confidence=0.45, status=AnswerStatus.CONFLICT)

q5 = Question(id=5, exam_id=999, index=5, local_image_path="data/raw/CSD202/exam_1_SU26/q05_Q5.webp")
# No answer object (no_data)

out = build_exam_docx("CSD202", exam, [q1, q2, q3, q4, q5], output_dir=Path("data/output/test_demo"))
print("Demo docx generated at:", out)

doc = Document(out)
for i in range(len(doc.paragraphs)):
    p = doc.paragraphs[i]
    if p.text.strip():
        runs_desc = " + ".join([f"[{r.text} | bold={r.bold} | {r.font.size.pt}pt | #{r.font.color.rgb}]" for r in p.runs])
        print(f"P{i:02d}: {runs_desc}")
