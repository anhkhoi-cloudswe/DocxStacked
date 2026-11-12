from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.db.models import Answer, AnswerStatus, Exam, ExamType, Job, JobStatus, Question, Subject
from backend.app.db.session import get_db
from backend.app.modules.jobs.orchestrator import get_orchestrator

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


class JobCreateRequest(BaseModel):
    subject_code: str = Field(..., description="Subject code, e.g. CSD202")
    exam_type: str = Field(default="FE", description="FE or PE")
    limit: int = Field(default=4, ge=1, le=50, description="Number of exams to compile (1-50)")
    force_refresh: bool = Field(default=False, description="Bypass document cache and force re-compilation")


class JobResponse(BaseModel):
    id: Optional[int] = None
    job_id: str
    subject_code: str
    exam_type: str
    exam_count: int
    status: str
    current_step: Optional[str] = None
    progress_percentage: float = 0.0
    error_message: Optional[str] = None
    result_file_path: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    config_snapshot: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AnswerItemOut(BaseModel):
    question_id: int
    question_index: int
    exam_id: int
    exam_title: Optional[str] = None
    final_answer: List[str]
    status: str
    confidence: float
    options: Dict[str, str] = {}
    community_votes: Dict[str, Any] = {}
    ai_vote: Optional[List[str]] = None
    manual_override: bool = False
    notes: Optional[str] = None


class SingleAnswerOverride(BaseModel):
    question_id: int
    answer: str = Field(..., description="Selected answer letter (e.g. 'A' or 'B')")
    notes: Optional[str] = None


class BatchAnswerOverrideRequest(BaseModel):
    answers: List[SingleAnswerOverride]


@router.get("", response_model=List[JobResponse])
async def list_recent_jobs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List recent compilation jobs ordered by created_at descending."""
    stmt = select(Job).order_by(desc(Job.created_at)).offset(offset).limit(limit)
    res = await db.execute(stmt)
    jobs = res.scalars().all()
    return [JobResponse.from_orm(j) for j in jobs]


@router.post("", response_model=JobResponse)
async def create_job(payload: JobCreateRequest):
    """Start a new exam compilation job."""
    e_type = ExamType.PE if payload.exam_type.upper() == "PE" else ExamType.FE
    orchestrator = get_orchestrator()
    job = await orchestrator.start_job(
        subject_code=payload.subject_code,
        exam_type=e_type,
        limit=payload.limit,
        force_refresh=payload.force_refresh,
    )
    return JobResponse.from_orm(job)


@router.get("/{job_id}", response_model=JobResponse)
async def get_job_status(job_id: str, db: AsyncSession = Depends(get_db)):
    """Get the current status of a job."""
    stmt = select(Job).where(Job.job_id == job_id)
    res = await db.execute(stmt)
    job = res.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse.from_orm(job)


@router.post("/{job_id}/cancel", response_model=JobResponse)
async def cancel_job_endpoint(job_id: str, db: AsyncSession = Depends(get_db)):
    """Cancel a running or pending compilation job."""
    orchestrator = get_orchestrator()
    await orchestrator.cancel_job(job_id)

    stmt = select(Job).where(Job.job_id == job_id)
    res = await db.execute(stmt)
    job = res.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse.from_orm(job)


@router.post("/{job_id}/resume", response_model=JobResponse)
async def resume_job_endpoint(job_id: str):
    """Resume a stopped or failed compilation job."""
    orchestrator = get_orchestrator()
    job = await orchestrator.resume_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found or cannot be resumed")
    return JobResponse.from_orm(job)


@router.get("/{job_id}/answers", response_model=List[AnswerItemOut])
async def get_job_answers(job_id: str, db: AsyncSession = Depends(get_db)):
    """
    Get all question answers for a job with community votes and AI predictions.
    """
    stmt = select(Job).where(Job.job_id == job_id)
    res = await db.execute(stmt)
    job = res.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    subj_code = job.subject_code.upper()
    subj_stmt = select(Subject).where(Subject.code == subj_code)
    subj_res = await db.execute(subj_stmt)
    subj = subj_res.scalar_one_or_none()

    if not subj:
        return []

    # Fetch exams of this subject
    exams_stmt = (
        select(Exam)
        .where(Exam.subject_id == subj.id, Exam.exam_type == job.exam_type)
        .order_by(desc(Exam.post_date), desc(Exam.id))
        .limit(job.exam_count)
    )
    exams_res = await db.execute(exams_stmt)
    exams = list(exams_res.scalars().all())
    exam_ids = [e.id for e in exams]

    if not exam_ids:
        return []

    # Fetch questions and answers
    q_stmt = (
        select(Question)
        .where(Question.exam_id.in_(exam_ids))
        .options(selectinload(Question.answer), selectinload(Question.exam))
        .order_by(Question.exam_id, Question.index)
    )
    q_res = await db.execute(q_stmt)
    questions = q_res.scalars().all()

    result: List[AnswerItemOut] = []
    for q in questions:
        ans = q.answer
        exam_title = q.exam.title if q.exam else None
        final_ans = ans.answer_set if ans else []
        conf = ans.confidence if ans else 0.0
        ans_status = ans.status.value if ans else "no_data"
        vb = ans.vote_breakdown if ans else {}

        options = vb.get("options", {})
        comm_votes = vb.get("community_votes", {})
        ai_vote = vb.get("ai_answers")
        is_manual = vb.get("manual_override", False)
        notes = ans.explanation if ans else None

        result.append(
            AnswerItemOut(
                question_id=q.id,
                question_index=q.index,
                exam_id=q.exam_id,
                exam_title=exam_title,
                final_answer=final_ans,
                status=ans_status,
                confidence=conf,
                options=options,
                community_votes=comm_votes,
                ai_vote=ai_vote,
                manual_override=is_manual,
                notes=notes,
            )
        )

    return result


@router.put("/{job_id}/answers")
async def update_job_answers(
    job_id: str,
    payload: Union[BatchAnswerOverrideRequest, SingleAnswerOverride],
    db: AsyncSession = Depends(get_db),
):
    """
    Manually override answers for questions in a job before exporting to Word.
    """
    items_to_update = payload.answers if isinstance(payload, BatchAnswerOverrideRequest) else [payload]
    updated_count = 0

    for item in items_to_update:
        ans_stmt = select(Answer).where(Answer.question_id == item.question_id)
        res = await db.execute(ans_stmt)
        ans = res.scalar_one_or_none()

        clean_choice = item.answer.strip().upper()
        if not ans:
            ans = Answer(
                question_id=item.question_id,
                answer_set=[clean_choice],
                confidence=1.0,
                status=AnswerStatus.CONFIDENT,
                vote_breakdown={"manual_override": True},
                explanation=item.notes,
            )
            db.add(ans)
        else:
            ans.answer_set = [clean_choice]
            ans.confidence = 1.0
            ans.status = AnswerStatus.CONFIDENT
            vb = dict(ans.vote_breakdown or {})
            vb["manual_override"] = True
            ans.vote_breakdown = vb
            ans.explanation = item.notes

        updated_count += 1

    await db.commit()
    return {"success": True, "updated_count": updated_count}


@router.get("/{job_id}/stream")
async def stream_job_events(job_id: str, db: AsyncSession = Depends(get_db)):
    """Stream real-time SSE progress events for a job."""
    stmt = select(Job).where(Job.job_id == job_id)
    res = await db.execute(stmt)
    job = res.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    orchestrator = get_orchestrator()
    return StreamingResponse(
        orchestrator.subscribe(job_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
