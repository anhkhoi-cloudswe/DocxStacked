from datetime import datetime
import re
from typing import List, Optional, Tuple
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Exam, ExamType, Subject
from backend.app.db.session import get_db
from backend.app.modules.crawler.exams import crawl_subject_exams
from backend.app.modules.crawler.subjects import (
    get_or_fetch_subjects,
    lookup_subject_by_code,
    strip_vietnamese_accents,
    sync_subjects_from_web,
)

router = APIRouter(prefix="/api/subjects", tags=["subjects"])


class SubjectOut(BaseModel):
    id: int
    code: str
    name: str
    forum_url: str
    exam_count: int
    last_synced_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SubjectListResponse(BaseModel):
    items: List[SubjectOut]
    total: int
    last_synced_at: Optional[datetime] = None


class SubjectLookupRequest(BaseModel):
    code: str = Field(..., min_length=2, max_length=20, description="Mã môn học, e.g. CSD202")


class SyncSubjectsResponse(BaseModel):
    success: bool
    added: int
    updated: int
    total: int
    last_synced_at: Optional[str] = None


class ExamOut(BaseModel):
    id: int
    subject_id: int
    title: str
    url: str
    exam_type: str
    term: Optional[str] = None
    post_date: Optional[datetime] = None
    question_count: int = 0

    class Config:
        from_attributes = True


@router.get("", response_model=SubjectListResponse)
async def list_subjects(
    q: Optional[str] = Query(None, description="Từ khoá tìm kiếm theo mã môn hoặc tên môn"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """
    Search and list subjects with accent-insensitive matching.
    Supports queries like 'cau truc' matching 'CSD202 - Cấu trúc dữ liệu'.
    """
    # Ensure database is seeded if empty
    all_subjects = await get_or_fetch_subjects(db)

    # Determine latest sync time across all subjects
    latest_sync = max((s.last_synced_at for s in all_subjects if s.last_synced_at), default=None)

    if q and q.strip():
        query_norm = strip_vietnamese_accents(q)
        filtered = [
            s for s in all_subjects
            if query_norm in strip_vietnamese_accents(s.code) or query_norm in strip_vietnamese_accents(s.name)
        ]
    else:
        filtered = all_subjects

    total = len(filtered)
    items = filtered[offset : offset + limit]

    return SubjectListResponse(
        items=[SubjectOut.from_orm(s) for s in items],
        total=total,
        last_synced_at=latest_sync,
    )


@router.post("/sync", response_model=SyncSubjectsResponse)
async def sync_subjects(db: AsyncSession = Depends(get_db)):
    """Trigger dynamic sync of all subjects from FuOverflow categories/subjects/."""
    result = await sync_subjects_from_web(db)
    return SyncSubjectsResponse(
        success=True,
        added=result["added"],
        updated=result["updated"],
        total=result["total"],
        last_synced_at=result["last_synced_at"],
    )


@router.post("/lookup", response_model=SubjectOut)
async def lookup_subject(
    payload: SubjectLookupRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Look up an unknown subject by code. If it exists on FuOverflow forum,
    it is added to the database automatically.
    """
    code = payload.code.strip().upper()
    subj = await lookup_subject_by_code(db, code)
    if not subj:
        raise HTTPException(
            status_code=404,
            detail=f"Không tìm thấy môn '{code}' trên diễn đàn FUOverflow. Vui lòng kiểm tra lại mã môn.",
        )
    return SubjectOut.from_orm(subj)


def get_semester_sort_key(
    term: Optional[str],
    post_date: Optional[datetime] = None,
    title: Optional[str] = None,
) -> Tuple[int, int, float]:
    """
    Sort key for academic semester ordering: SU26 > SP26 > FA25 > SU25...
    Seasons: FA (Fall/Thu) = 3, SU (Summer/Hè) = 2, SP (Spring/Xuân) = 1, WI (Winter) = 0.
    """
    season_weights = {"FA": 3, "SU": 2, "SP": 1, "WI": 0}
    year = 0
    season_weight = 0

    text_to_search = f"{term or ''} {title or ''}".strip()
    if text_to_search:
        m = re.search(r"\b(SU|FA|SP|WI)\s*(\d{2,4})\b", text_to_search, re.IGNORECASE)
        if m:
            s_code = m.group(1).upper()
            y_val = int(m.group(2))
            if y_val < 100:
                y_val += 2000
            year = y_val
            season_weight = season_weights.get(s_code, 0)

    # Fallback to post_date if no term found
    if year == 0 and post_date:
        year = post_date.year
        # Guess semester from month: 1-4: SP, 5-8: SU, 9-12: FA
        month = post_date.month
        if month >= 9:
            season_weight = 3
        elif month >= 5:
            season_weight = 2
        else:
            season_weight = 1

    timestamp = post_date.timestamp() if post_date else 0.0
    return (year, season_weight, timestamp)


@router.get("/{code}/exams", response_model=List[ExamOut])
async def list_subject_exams(
    code: str,
    type: str = Query("FE", pattern="^(FE|PE)$", description="Loại đề (FE hoặc PE)"),
    db: AsyncSession = Depends(get_db),
):
    """
    Get real list of exams for a subject sorted newest first by semester (SU26 > SP26 > FA25).
    """
    clean_code = code.strip().upper()
    stmt = select(Subject).where(Subject.code == clean_code)
    res = await db.execute(stmt)
    subj = res.scalar_one_or_none()

    if not subj:
        subj = await lookup_subject_by_code(db, clean_code)
        if not subj:
            raise HTTPException(status_code=404, detail=f"Môn '{clean_code}' không tồn tại trong hệ thống.")

    exam_type_enum = ExamType.FE if type.upper() == "FE" else ExamType.PE

    # Check existing exams in DB
    exam_stmt = select(Exam).where(Exam.subject_id == subj.id, Exam.exam_type == exam_type_enum)
    exam_res = await db.execute(exam_stmt)
    exams = list(exam_res.scalars().all())

    # If no exams found in DB yet, try crawling page 1
    if not exams:
        try:
            exams = await crawl_subject_exams(subj, exam_type=exam_type_enum, limit=20, db=db)
        except Exception:
            pass

    # Sort exams newest first by semester (SU26 > SP26 > FA25)
    sorted_exams = sorted(
        exams,
        key=lambda e: get_semester_sort_key(e.term, e.post_date, e.title),
        reverse=True,
    )

    return [ExamOut.from_orm(e) for e in sorted_exams]
