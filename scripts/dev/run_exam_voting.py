import asyncio
from sqlalchemy import select
from backend.app.db.models import Answer, AnswerStatus, Exam, Question
from backend.app.db.session import async_session_factory
from backend.app.modules.analysis.voting import tally_votes

async def main():
    async with async_session_factory() as db:
        # Load Exam 1 questions with comments
        stmt = select(Question).where(Question.exam_id == 1).order_by(Question.index)
        res = await db.execute(stmt)
        questions = list(res.scalars().all())

        print(f"Loaded {len(questions)} questions for Exam CSD202.\n")
        stats = {AnswerStatus.CONFIDENT: 0, AnswerStatus.WEAK: 0, AnswerStatus.CONFLICT: 0, AnswerStatus.NO_DATA: 0}

        for q in questions:
            # Load comments for this question
            await db.refresh(q, ["comments", "answer"])
            voting_res = tally_votes(q.comments)

            # Update or create Answer record
            if not q.answer:
                ans = Answer(
                    question_id=q.id,
                    answer_set=voting_res.answer_set,
                    status=voting_res.status,
                    confidence=voting_res.confidence,
                    valid_comments_count=voting_res.voters_count,
                    vote_breakdown=voting_res.vote_breakdown,
                )
                db.add(ans)
            else:
                q.answer.answer_set = voting_res.answer_set
                q.answer.status = voting_res.status
                q.answer.confidence = voting_res.confidence
                q.answer.valid_comments_count = voting_res.voters_count
                q.answer.vote_breakdown = voting_res.vote_breakdown

            stats[voting_res.status] += 1
            print(f"Q{q.index:02d}: Ans={','.join(voting_res.answer_set):<4} Status={voting_res.status.value:<10} Conf={voting_res.confidence:<5.2f} Voters={voting_res.voters_count} Breakdown={voting_res.vote_breakdown}")

        await db.commit()
        print("\n=== SUMMARY FOR CSD202 EXAM ===")
        print(f"Total Questions: {len(questions)}")
        for st, count in stats.items():
            print(f"  {st.value.upper()}: {count} questions ({count/len(questions)*100:.1f}%)")

if __name__ == "__main__":
    asyncio.run(main())
