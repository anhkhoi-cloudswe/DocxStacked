import pytest
from httpx import AsyncClient, ASGITransport

from backend.app.main import app
from backend.app.db.models import Answer, AnswerStatus, Exam, ExamType, Job, JobStatus, Question, Subject
from backend.app.db.session import async_session_factory, init_db


@pytest.fixture(autouse=True)
async def setup_test_db():
    await init_db()


@pytest.mark.asyncio
async def test_auth_status_endpoint():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/auth/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "logged_in" in data
        assert isinstance(data["logged_in"], bool)


@pytest.mark.asyncio
async def test_jobs_list_cancel_resume_flow():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create a job
        create_resp = await client.post("/api/jobs", json={
            "subject_code": "CSD202",
            "exam_type": "FE",
            "limit": 2,
        })
        assert create_resp.status_code == 200
        job_data = create_resp.json()
        job_id = job_data["job_id"]
        assert job_id is not None

        # 2. List jobs (GET /api/jobs)
        list_resp = await client.get("/api/jobs")
        assert list_resp.status_code == 200
        jobs = list_resp.json()
        assert isinstance(jobs, list)
        assert any(j["job_id"] == job_id for j in jobs)

        # 3. Cancel job (POST /api/jobs/{id}/cancel)
        cancel_resp = await client.post(f"/api/jobs/{job_id}/cancel")
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["status"] == "failed"

        # 4. Resume job (POST /api/jobs/{id}/resume)
        resume_resp = await client.post(f"/api/jobs/{job_id}/resume")
        assert resume_resp.status_code == 200
        assert resume_resp.json()["status"] in ("pending", "running")

        # Cleanup: cancel resumed job so background task does not lock DB for subsequent tests
        await client.post(f"/api/jobs/{job_id}/cancel")


@pytest.mark.asyncio
async def test_job_answers_and_manual_override():
    import uuid
    code = f"T{uuid.uuid4().hex[:5].upper()}"
    job_uuid = f"job-{uuid.uuid4().hex[:8]}"

    # Seed DB with a subject, exam, question and answer
    async with async_session_factory() as db:
        subj = Subject(code=code, name="Test Subject", forum_url=f"https://fuoverflow.com/forums/{code}/")
        db.add(subj)
        await db.flush()

        exam = Exam(subject_id=subj.id, title=f"{code} FE", url=f"https://fuoverflow.com/threads/{code.lower()}.88888/", exam_type=ExamType.FE)
        db.add(exam)
        await db.flush()

        q = Question(exam_id=exam.id, index=1, file_name="Q1.png")
        db.add(q)
        await db.flush()

        ans = Answer(
            question_id=q.id,
            answer_set=["A"],
            confidence=0.6,
            status=AnswerStatus.WEAK,
            vote_breakdown={"options": {"A": "First opt", "B": "Second opt"}, "community_votes": {"A": 1}},
        )
        db.add(ans)

        job = Job(
            job_id=job_uuid,
            subject_code=code,
            exam_type=ExamType.FE,
            exam_count=1,
            status=JobStatus.COMPLETED,
        )
        db.add(job)
        await db.commit()
        q_id = q.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. GET /api/jobs/{id}/answers
        get_ans_resp = await client.get(f"/api/jobs/{job_uuid}/answers")
        assert get_ans_resp.status_code == 200
        answers = get_ans_resp.json()
        assert len(answers) >= 1
        q_item = next(a for a in answers if a["question_id"] == q_id)
        assert q_item["final_answer"] == ["A"]
        assert q_item["status"] == "weak"

        # 2. PUT /api/jobs/{id}/answers: override with "B"
        put_ans_resp = await client.put(f"/api/jobs/{job_uuid}/answers", json={
            "answers": [
                {
                    "question_id": q_id,
                    "answer": "B",
                    "notes": "Verified by student manually"
                }
            ]
        })
        assert put_ans_resp.status_code == 200
        assert put_ans_resp.json()["success"] is True

        # 3. GET again and verify overridden answer
        get_ans_resp2 = await client.get(f"/api/jobs/{job_uuid}/answers")
        answers2 = get_ans_resp2.json()
        q_item2 = next(a for a in answers2 if a["question_id"] == q_id)
        assert q_item2["final_answer"] == ["B"]
        assert q_item2["status"] == "confident"
        assert q_item2["manual_override"] is True
        assert q_item2["notes"] == "Verified by student manually"


@pytest.mark.asyncio
async def test_exports_endpoints():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. GET /api/exports
        resp = await client.get("/api/exports")
        assert resp.status_code == 200
        exports = resp.json()
        assert isinstance(exports, list)
        if len(exports) > 0:
            first = exports[0]
            assert "filename" in first
            assert "download_url" in first

        # 2. GET /api/exports/bundle.zip
        resp_zip = await client.get("/api/exports/bundle.zip")
        # Should return 200 if docx files exist, or 404 if directory empty
        assert resp_zip.status_code in (200, 404)
        if resp_zip.status_code == 200:
            assert resp_zip.headers["content-type"] == "application/zip"


@pytest.mark.asyncio
async def test_user_endpoints():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. GET /api/user/me
        resp_me = await client.get("/api/user/me")
        assert resp_me.status_code == 200
        me = resp_me.json()
        assert "username" in me
        assert "total_documents" in me

        # 2. GET /api/user/documents
        resp_docs = await client.get("/api/user/documents")
        assert resp_docs.status_code == 200
        docs = resp_docs.json()
        assert isinstance(docs, list)
        if len(docs) > 0:
            assert "filename" in docs[0]
            assert "download_url" in docs[0]
            assert "subject_code" in docs[0]
