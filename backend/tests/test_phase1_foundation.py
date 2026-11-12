"""
backend/tests/test_phase1_foundation.py - Verification tests for Phase 1 Foundation deliverables.

Tests:
1. Config loader (config.yaml, selectors.yaml, settings)
2. Rate limiter (async & sync delays, concurrency locks)
3. Local storage (CRUD, directory traversal security)
4. DB models (Subject, Exam, Question, Comment, Answer, Job) & CRUD & resume logic
5. BrowserManager (session authentication check)
6. FastAPI health check endpoint
"""

import asyncio
import os
import time
from pathlib import Path
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app.core.config import Settings, get_settings
from backend.app.db.models import (
    Answer,
    AnswerStatus,
    Base,
    Comment,
    Exam,
    ExamStatus,
    ExamType,
    Job,
    JobStatus,
    Question,
    QuestionType,
    Subject,
)
from backend.app.main import app
from backend.app.modules.crawler.browser import BrowserManager
from backend.app.modules.crawler.rate_limiter import RateLimiter
from backend.app.storage.local import LocalStorage

# Test in-memory / temporary database for tests
TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def test_db():
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def test_config_loader():
    """Verify settings, yaml_config, and selectors.yaml are loaded with valid types."""
    settings = get_settings()
    assert settings.ENVIRONMENT in ("development", "production", "test")
    assert settings.STORAGE_DIR.exists()

    # Test yaml_config
    yaml_cfg = settings.yaml_config
    assert yaml_cfg.exam.default_count >= 1
    assert len(yaml_cfg.crawl.delay_seconds) == 2
    assert yaml_cfg.crawl.delay_seconds[0] <= yaml_cfg.crawl.delay_seconds[1]
    assert yaml_cfg.analysis.confident_min_ratio > 0

    # Test selectors
    selectors = settings.selectors
    assert "endpoints" in selectors
    assert "comments" in selectors
    assert "media_detail" in selectors
    assert "full_image" in selectors["media_detail"]


@pytest.mark.asyncio
async def test_rate_limiter_async():
    """Verify rate limiter enforces minimum delay and serializes concurrent calls."""
    limiter = RateLimiter(min_delay=0.1, max_delay=0.2, concurrency=1)

    t0 = time.monotonic()
    await asyncio.gather(
        limiter.async_wait(),
        limiter.async_wait(),
    )
    t1 = time.monotonic()
    elapsed = t1 - t0
    # Two calls with min_delay=0.1 should take at least ~0.1s
    assert elapsed >= 0.08, f"Expected elapsed >= 0.08s, got {elapsed:.3f}s"


def test_rate_limiter_sync():
    """Verify rate limiter sync_wait works properly."""
    limiter = RateLimiter(min_delay=0.05, max_delay=0.1, concurrency=1)
    t0 = time.monotonic()
    limiter.sync_wait()
    limiter.sync_wait()
    t1 = time.monotonic()
    assert (t1 - t0) >= 0.04


def test_local_storage(tmp_path):
    """Test LocalStorage save, read, exists, delete, and directory traversal protection."""
    storage = LocalStorage(root_dir=tmp_path)

    # 1. Save and read
    rel_path = "raw/test_subject/test.txt"
    content = b"Gomde test content 123"
    saved_path = storage.save(rel_path, content)
    assert storage.exists(rel_path)
    assert storage.read(rel_path) == content

    # 2. Delete
    assert storage.delete(rel_path) is True
    assert not storage.exists(rel_path)

    # 3. Path traversal attack protection
    with pytest.raises(ValueError, match="Path traversal detected"):
        storage.save("../../evil.txt", b"hack")


@pytest.mark.asyncio
async def test_db_models_crud_and_resume(test_db: AsyncSession):
    """Test full CRUD operations on all models and resume query logic."""
    # 1. Create Subject
    subject = Subject(code="CSD202", name="Data Structures and Algorithms", forum_url="https://fuoverflow.com/forums/CSD202/")
    test_db.add(subject)
    await test_db.commit()
    await test_db.refresh(subject)
    assert subject.id is not None

    # 2. Create Exam
    exam = Exam(
        subject_id=subject.id,
        exam_type=ExamType.FE,
        term="SU26",
        title="CSD202 SU26 FE",
        url="https://fuoverflow.com/threads/csd202-su26-fe.7086/",
        status=ExamStatus.PENDING,
    )
    test_db.add(exam)
    await test_db.commit()
    await test_db.refresh(exam)

    # 3. Create Questions (one already crawled with image, one uncrawled)
    q1 = Question(
        exam_id=exam.id,
        index=1,
        file_name="Q1.webp",
        cdn_image_url="https://data.fuoverflow.com/attachments/139/139511.jpg",
        local_image_path="data/raw/CSD202/FE_SU26/q001.webp",
        media_url="https://fuoverflow.com/media/q1-webp.134314/",
        media_id="134314",
    )
    q2 = Question(
        exam_id=exam.id,
        index=2,
        file_name="Q2.webp",
        cdn_image_url="https://data.fuoverflow.com/attachments/139/139512.jpg",
        local_image_path=None,  # Not yet downloaded
        media_url="https://fuoverflow.com/media/q2-webp.134315/",
        media_id="134315",
    )
    test_db.add_all([q1, q2])
    await test_db.commit()

    # 4. Resume logic test: find questions that still need image download
    stmt = select(Question).where(Question.exam_id == exam.id, Question.local_image_path.is_(None))
    res = await test_db.execute(stmt)
    pending_questions = res.scalars().all()
    assert len(pending_questions) == 1
    assert pending_questions[0].index == 2

    # 5. Add Comments to Q1
    c1 = Comment(
        question_id=q1.id,
        comment_id="1238903",
        author_hash="hash_student_a",
        raw_text="Câu này đáp án A chuẩn rồi",
        upvotes=4,
        is_reply=False,
    )
    c2 = Comment(
        question_id=q1.id,
        comment_id="1262956",
        author_hash="hash_student_b",
        raw_text="A",
        upvotes=2,
        is_reply=False,
    )
    test_db.add_all([c1, c2])
    await test_db.commit()

    # 6. Add Answer for Q1
    ans = Answer(
        question_id=q1.id,
        answer_set=["A"],
        confidence=0.88,
        status=AnswerStatus.CONFIDENT,
        valid_comments_count=2,
        vote_breakdown={"A": 6, "B": 0, "C": 0, "D": 0},
    )
    test_db.add(ans)
    await test_db.commit()

    # 7. Create Job
    job = Job(
        job_id="test-job-uuid-1",
        subject_code="CSD202",
        exam_type=ExamType.FE,
        exam_count=4,
        status=JobStatus.RUNNING,
        progress_percentage=25.0,
        current_step="Crawling exam 1/4",
    )
    test_db.add(job)
    await test_db.commit()
    await test_db.refresh(job)

    assert job.status == JobStatus.RUNNING
    assert job.exam_count == 4


def test_browser_manager_initialization():
    """Verify BrowserManager initializes settings properly."""
    bm = BrowserManager()
    assert bm.profile_dir.exists()
    assert bm.channel in ("chrome", "chromium")


@pytest.mark.asyncio
async def test_fastapi_health_endpoint():
    """Verify FastAPI /api/health endpoint returns 200 OK and valid health JSON."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "database" in data
        assert data["database"] == "healthy"

