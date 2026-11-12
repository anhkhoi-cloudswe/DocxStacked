from pathlib import Path
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app.db.models import Base, Exam, ExamType, Question, QuestionType
from backend.app.modules.crawler.questions import crawl_exam_questions
from backend.app.storage.local import LocalStorage


@pytest.mark.asyncio
async def test_crawl_exam_questions_dedup_complete(tmp_path: Path, monkeypatch):
    """
    Test that when all questions already exist in DB with valid local files (>500 bytes),
    crawl_exam_questions returns them immediately without fetching the thread HTML.
    """
    test_db_url = f"sqlite+aiosqlite:///{tmp_path}/test_q_dedup.db"
    engine = create_async_engine(test_db_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    from backend.app.core import config
    mock_settings = config.get_settings()
    monkeypatch.setattr(mock_settings, "STORAGE_DIR", tmp_path / "data")
    monkeypatch.setattr(mock_settings, "BASE_DIR", tmp_path)

    # Create dummy images on disk (> 8000 bytes)
    img_dir = tmp_path / "data" / "raw" / "CSD202" / "exam_1_fe"
    img_dir.mkdir(parents=True, exist_ok=True)
    img1 = img_dir / "q01_Q1.webp"
    img2 = img_dir / "q02_Q2.webp"
    img1.write_bytes(b"x" * 16384)
    img2.write_bytes(b"x" * 16384)

    rel_img1 = str(img1.relative_to(tmp_path)).replace("\\", "/")
    rel_img2 = str(img2.relative_to(tmp_path)).replace("\\", "/")

    async with session_maker() as db:
        exam = Exam(
            id=1,
            subject_id=1,
            title="CSD202 - SU26 - FE",
            term="SU26",
            url="https://fuoverflow.com/threads/test.1/",
            exam_type=ExamType.FE,
            question_count=2,
        )
        q1 = Question(
            id=1,
            exam_id=1,
            index=1,
            file_name="Q1.webp",
            local_image_path=rel_img1,
            qtype=QuestionType.SINGLE,
        )
        q2 = Question(
            id=2,
            exam_id=1,
            index=2,
            file_name="Q2.webp",
            local_image_path=rel_img2,
            qtype=QuestionType.SINGLE,
        )
        db.add_all([exam, q1, q2])
        await db.commit()

        storage = LocalStorage()
        progress_records = []

        def on_prog(cur, tot, msg):
            progress_records.append((cur, tot, msg))

        # Should return existing without hitting network
        result_qs = await crawl_exam_questions(
            exam=exam,
            subject_code="CSD202",
            db=db,
            storage=storage,
            on_progress=on_prog,
        )

        assert len(result_qs) == 2
        assert result_qs[0].index == 1
        assert result_qs[1].index == 2
        assert len(progress_records) == 1
        assert "bỏ qua" in progress_records[0][2] or "Đã có đủ" in progress_records[0][2]

    await engine.dispose()
