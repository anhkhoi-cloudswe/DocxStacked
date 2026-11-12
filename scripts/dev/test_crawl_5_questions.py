import asyncio
from backend.app.db.session import async_session_factory
from backend.app.db.models import Exam, Question
from backend.app.modules.crawler.comments import crawl_question_comments
from sqlalchemy import select

async def main():
    async with async_session_factory() as db:
        stmt = select(Question).where(Question.exam_id == 1).order_by(Question.index).limit(5)
        questions = list((await db.execute(stmt)).scalars().all())
        print(f"Found {len(questions)} questions to test crawl.")
        
        for q in questions:
            print(f"\n--- Crawling Q{q.index} ({q.media_url}) ---")
            cmts = await crawl_question_comments(
                question=q,
                subject_code="CSD202",
                exam_slug="exam_1_fe",
                db=db,
                force_refresh=False,
            )
            print(f"Result for Q{q.index}: {len(cmts)} comments")
            for c in cmts:
                print(f"  Comment: ID={c.comment_id}, upvotes={c.upvotes}, is_reply={c.is_reply}, quoted={c.quoted_comment_id}, text='{c.raw_text}'")

if __name__ == "__main__":
    asyncio.run(main())

