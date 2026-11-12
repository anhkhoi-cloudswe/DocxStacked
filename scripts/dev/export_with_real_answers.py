import asyncio
from sqlalchemy import select
from backend.app.db.models import Exam, Question
from backend.app.db.session import async_session_factory
from backend.app.modules.export.docx_builder import build_exam_docx

async def main():
    async with async_session_factory() as db:
        stmt = select(Exam).where(Exam.id == 1)
        exam = (await db.execute(stmt)).scalar_one_or_none()
        
        stmt_q = select(Question).where(Question.exam_id == 1).order_by(Question.index)
        questions = list((await db.execute(stmt_q)).scalars().all())
        for q in questions:
            await db.refresh(q, ["answer"])
            
        print(f"Building docx for {exam.title} with {len(questions)} questions with real answers...")
        out_path = build_exam_docx("CSD202", exam, questions)
        print(f"Generated: {out_path} ({out_path.stat().st_size} bytes)")

if __name__ == "__main__":
    asyncio.run(main())

