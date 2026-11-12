from pathlib import Path
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app.db.models import Base, Comment, Exam, ExamType, Question, QuestionType
from backend.app.modules.crawler.comments import (
    crawl_exam_comments,
    crawl_question_comments,
    parse_comments_from_html,
)

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def test_parse_comments_with_reactions():
    fixture_path = FIXTURES_DIR / "media_q11-webp_137454_clean.html"
    assert fixture_path.exists()

    html_content = fixture_path.read_text(encoding="utf-8")
    comments = parse_comments_from_html(html_content, question_id=1, html_path="test/path.html")

    assert len(comments) == 14

    # Comment 6 has reactions: 'anhduy , Đỗ Quang Minh , hoan@2915 and 2 others' = 5 upvotes
    c6 = comments[5]
    assert c6.comment_id == "1265171"
    assert c6.upvotes == 5
    assert len(c6.author_hash) == 16
    assert c6.html_path == "test/path.html"
    assert "chứ không bao gồm" in c6.raw_text

    # Comment 11 has reaction: 'Kajazi' = 1 upvote
    c11 = comments[10]
    assert c11.comment_id == "1266392"
    assert c11.upvotes == 1
    assert c11.raw_text == "B"


def test_parse_comments_with_nested_quote():
    html_sample = """
    <div class="message message--comment" data-content="media-comment-99901">
      <div class="message-name"><span class="username">Student_Tester</span></div>
      <div class="message-body">
        <div class="bbWrapper">
          <blockquote class="bbCodeBlock bbCodeBlock--quote" data-quote="Original_Poster">
            <div class="bbCodeBlock-title"><a href="/media/comments/1265171/">Original_Poster said:</a></div>
            <div class="bbCodeBlock-content">Đáp án câu này chắc chắn là B nhé.</div>
          </blockquote>
          +1 chuẩn luôn bác ơi!
        </div>
      </div>
      <div class="reactionsBar js-reactionsList is-active">
        <a class="reactionsBar-link" href="/media/comments/99901/reactions">
          <bdi>Student_A</bdi> and 2 others
        </a>
      </div>
    </div>
    """
    comments = parse_comments_from_html(html_sample, question_id=42)
    assert len(comments) == 1

    c = comments[0]
    assert c.comment_id == "99901"
    assert c.is_reply is True
    assert c.quoted_comment_id == 1265171
    # Ensure blockquote text is removed and only own text is kept
    assert c.raw_text == "+1 chuẩn luôn bác ơi!"
    assert "Đáp án câu này chắc chắn là B" not in c.raw_text
    # 1 named + 2 others = 3 upvotes
    assert c.upvotes == 3


@pytest.mark.asyncio
async def test_crawl_question_comments_resume_from_disk(tmp_path: Path, monkeypatch):
    # Setup test DB engine
    test_db_url = f"sqlite+aiosqlite:///{tmp_path}/test_comments.db"
    engine = create_async_engine(test_db_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    # Monkeypatch settings storage dir
    from backend.app.core import config
    mock_settings = config.get_settings()
    monkeypatch.setattr(mock_settings, "STORAGE_DIR", tmp_path / "data")
    monkeypatch.setattr(mock_settings, "BASE_DIR", tmp_path)

    # Pre-populate raw HTML cache
    comments_dir = tmp_path / "data" / "raw" / "CSD202" / "exam_1_fe" / "comments"
    comments_dir.mkdir(parents=True, exist_ok=True)
    cached_html = comments_dir / "q001_134314.html"

    fixture_src = FIXTURES_DIR / "media_q1-webp_134314_clean.html"
    cached_html.write_text(fixture_src.read_text(encoding="utf-8"), encoding="utf-8")

    async with session_maker() as db:
        exam = Exam(
            id=1,
            subject_id=1,
            title="CSD202 - SU26 - FE",
            term="SU26",
            url="https://fuoverflow.com/threads/test.1/",
            exam_type=ExamType.FE,
        )
        q = Question(
            id=1,
            exam_id=1,
            index=1,
            file_name="Q1.webp",
            qtype=QuestionType.SINGLE,
            media_id="134314",
            media_url="https://fuoverflow.com/media/q1-webp.134314/",
        )
        db.add_all([exam, q])
        await db.commit()

        # Crawl comments - should resume from cached_html without hitting network
        cmts = await crawl_question_comments(
            question=q,
            subject_code="CSD202",
            exam_slug="exam_1_fe",
            db=db,
            force_refresh=False,
        )

        assert len(cmts) == 2
        assert cmts[0].raw_text == "a"

        # Verify persisted in DB
        stmt = select(Comment).where(Comment.question_id == q.id)
        db_cmts = (await db.execute(stmt)).scalars().all()
        assert len(db_cmts) == 2

    await engine.dispose()


@pytest.mark.asyncio
async def test_crawl_exam_comments_batch(tmp_path: Path, monkeypatch):
    test_db_url = f"sqlite+aiosqlite:///{tmp_path}/test_batch_comments.db"
    engine = create_async_engine(test_db_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    from backend.app.core import config
    from backend.app.modules.crawler.comments import crawl_exam_comments
    mock_settings = config.get_settings()
    monkeypatch.setattr(mock_settings, "STORAGE_DIR", tmp_path / "data")
    monkeypatch.setattr(mock_settings, "BASE_DIR", tmp_path)

    comments_dir = tmp_path / "data" / "raw" / "CSD202" / "exam_1_SU26" / "comments"
    comments_dir.mkdir(parents=True, exist_ok=True)

    # Put 2 fixture HTML files in cache
    f1 = FIXTURES_DIR / "media_q1-webp_134314_clean.html"
    f2 = FIXTURES_DIR / "media_q2-webp_134315_clean.html"
    (comments_dir / "q001_134314.html").write_text(f1.read_text(encoding="utf-8"), encoding="utf-8")
    (comments_dir / "q002_134315.html").write_text(f2.read_text(encoding="utf-8"), encoding="utf-8")

    async with session_maker() as db:
        exam = Exam(
            id=1,
            subject_id=1,
            title="CSD202 - SU26 - FE",
            term="SU26",
            url="https://fuoverflow.com/threads/test.1/",
            exam_type=ExamType.FE,
        )
        q1 = Question(
            id=1,
            exam_id=1,
            index=1,
            file_name="Q1.webp",
            qtype=QuestionType.SINGLE,
            media_id="134314",
            media_url="https://fuoverflow.com/media/q1-webp.134314/",
        )
        q2 = Question(
            id=2,
            exam_id=1,
            index=2,
            file_name="Q2.webp",
            qtype=QuestionType.SINGLE,
            media_id="134315",
            media_url="https://fuoverflow.com/media/q2-webp.134315/",
        )
        db.add_all([exam, q1, q2])
        await db.commit()

        progress_calls = []

        def on_prog(cur, tot, msg):
            progress_calls.append((cur, tot, msg))

        all_cmts = await crawl_exam_comments(
            exam=exam,
            subject_code="CSD202",
            db=db,
            on_progress=on_prog,
            force_refresh=False,
        )

        assert len(all_cmts) == 4  # 2 comments for Q1 + 2 comments for Q2
        assert len(progress_calls) == 2
        assert progress_calls[0] == (1, 2, "Q1: 2 comments")
        assert progress_calls[1] == (2, 2, "Q2: 2 comments")

    await engine.dispose()


@pytest.mark.asyncio
async def test_crawl_exam_comments_dedup_skip(tmp_path: Path):
    test_db_url = f"sqlite+aiosqlite:///{tmp_path}/test_dedup_comments.db"
    engine = create_async_engine(test_db_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with session_maker() as db:
        exam = Exam(
            id=10,
            subject_id=1,
            title="TEST - SU26 - FE",
            term="SU26",
            url="https://fuoverflow.com/threads/test.10/",
            exam_type=ExamType.FE,
        )
        q1 = Question(
            id=101,
            exam_id=10,
            index=1,
            file_name="Q1.webp",
            qtype=QuestionType.SINGLE,
            media_id="9991",
        )
        c1 = Comment(
            id=1,
            question_id=101,
            comment_id="c1",
            author_hash="testhash12345678",
            raw_text="Answer A",
            upvotes=3,
        )
        db.add_all([exam, q1, c1])
        await db.commit()

        # Should skip immediately because Q101 already has comments in DB
        res = await crawl_exam_comments(exam=exam, subject_code="TEST", db=db, force_refresh=False)
        assert len(res) == 1
        assert res[0].raw_text == "Answer A"

    await engine.dispose()
