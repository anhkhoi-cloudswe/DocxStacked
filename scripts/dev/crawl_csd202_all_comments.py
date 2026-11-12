import asyncio
import sys
from backend.app.db.session import async_session_factory
from backend.app.db.models import Exam
from backend.app.modules.crawler.comments import crawl_exam_comments
from sqlalchemy import select

async def main():
    async with async_session_factory() as db:
        stmt = select(Exam).where(Exam.id == 1)
        exam = (await db.execute(stmt)).scalar_one_or_none()
        if not exam:
            print("Exam 1 not found")
            return
            
        print(f"Starting crawl_exam_comments for Exam ID 1: {exam.title}...")
        
        def on_prog(cur, tot, msg):
            print(f"[{cur}/{tot}] {msg}")
            sys.stdout.flush()
            
        comments = await crawl_exam_comments(
            exam=exam,
            subject_code="CSD202",
            db=db,
            on_progress=on_prog,
            force_refresh=False,
        )
        print(f"\nDone! Crawled a total of {len(comments)} comments across all questions.")

if __name__ == "__main__":
    asyncio.run(main())

