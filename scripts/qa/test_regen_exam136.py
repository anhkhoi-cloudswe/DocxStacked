import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath('.'))

from backend.app.db.session import async_session_factory
from backend.app.db.models import Exam, Question, Answer, Subject
from backend.app.modules.export.docx_builder import build_exam_docx
from sqlalchemy import select
from sqlalchemy.orm import selectinload
import docx

async def test_regen():
    async with async_session_factory() as db:
        exam = await db.get(Exam, 136)
        subj = await db.get(Subject, exam.subject_id)
        q_res = await db.execute(
            select(Question)
            .where(Question.exam_id == 136)
            .options(selectinload(Question.comments))
            .order_by(Question.index)
        )
        questions = q_res.scalars().all()
        
        ans_res = await db.execute(select(Answer).where(Answer.question_id.in_([q.id for q in questions])))
        answers = ans_res.scalars().all()
        answers_map = {a.question_id: a for a in answers}

        temp_out = Path('data/output/MLN122/temp_test_regen')
        temp_out.mkdir(parents=True, exist_ok=True)

        docx_path = build_exam_docx(
            subject_code=subj.code,
            exam=exam,
            questions=questions,
            output_dir=temp_out,
            answers_map=answers_map
        )
        print(f"Generated docx: {docx_path}, Size: {docx_path.stat().st_size} bytes")

        ref_doc = docx.Document('data/output/MLN122/MLN122 - SU26 - RE.docx')
        gen_doc = docx.Document(docx_path)

        def extract_answers(doc):
            ans = []
            for p in doc.paragraphs:
                t = p.text.strip()
                if t and not t.startswith('Câu ') and not t.startswith('==='):
                    ans.append(t)
            return ans

        ref_ans = extract_answers(ref_doc)
        gen_ans = extract_answers(gen_doc)

        print(f"Ref answers count: {len(ref_ans)}, Gen answers count: {len(gen_ans)}")
        diffs = 0
        for i, (r, g) in enumerate(zip(ref_ans, gen_ans)):
            if r != g:
                diffs += 1
                print(f"Diff at q{i+1}: ref='{r}' vs gen='{g}'")
        print(f"Total answer differences: {diffs}")

        import shutil
        shutil.rmtree(temp_out)

if __name__ == '__main__':
    asyncio.run(test_regen())
