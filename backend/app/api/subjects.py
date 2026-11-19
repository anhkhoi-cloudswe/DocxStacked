from datetime import datetime, timezone
import re
from typing import List, Optional, Tuple
from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.db.models import Exam, ExamStatus, ExamType, Subject
from backend.app.db.session import get_db
from backend.app.api.ingest import clean_exam_title, extract_thread_id
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
    compiled: bool = False
    has_file: bool = False
    missing_file: bool = False
    download_url: Optional[str] = None
    compiled_at: Optional[str] = None
    compiled_at_iso: Optional[str] = None

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


@router.post("/parse-forum-html")
async def parse_forum_html(
    payload: dict,
    db: AsyncSession = Depends(get_db),
):
    """
    Parse FuOverflow forum HTML fetched in browser session (with cookies)
    and match threads against DB to return compilation status.
    """
    html = payload.get("html", "")
    subject_code = (payload.get("subject_code") or "").strip().upper()
    if not html:
        raise HTTPException(status_code=400, detail="Missing HTML content")

    soup = BeautifulSoup(html, "html.parser")
    thread_items = soup.select(".structItemContainer .structItem--thread")

    # Lookup subject
    subj = None
    if subject_code:
        stmt = select(Subject).where(Subject.code == subject_code)
        res = await db.execute(stmt)
        subj = res.scalar_one_or_none()

    # Get all compiled exams for this subject if available
    db_exams_by_url = {}
    db_exams_by_tid = {}
    if subj:
        exam_stmt = select(Exam).where(Exam.subject_id == subj.id)
        exam_res = await db.execute(exam_stmt)
        for ex in exam_res.scalars().all():
            db_exams_by_url[ex.url.rstrip("/")] = ex
            ex_tid = extract_thread_id(ex.url)
            if ex_tid:
                db_exams_by_tid[ex_tid] = ex

    results = []
    for item in thread_items:
        title_el = item.select_one(".structItem-title a[href^='/threads/']:not([href$='/latest'])")
        if not title_el:
            continue

        raw_title = title_el.get_text(strip=True)
        cleaned_title = clean_exam_title(raw_title)
        href = title_el.get("href", "")
        thread_url = f"https://fuoverflow.com{href}" if href.startswith("/") else href
        norm_url = thread_url.rstrip("/")
        tid = extract_thread_id(thread_url)

        badge_el = item.select_one(".label")
        badge_text = badge_el.get_text(strip=True).upper() if badge_el else ""

        is_fe = "FE" in badge_text or "RE" in badge_text or "-fe." in href.lower() or "-re." in href.lower() or "fe" in raw_title.lower() or "re" in raw_title.lower()
        is_pe = "PE" in badge_text or "-pe-" in href.lower() or "-pe." in href.lower() or "pe" in raw_title.lower()

        if is_fe:
            exam_type = "FE"
        elif is_pe:
            exam_type = "PE"
        else:
            exam_type = "FE"  # Default fallback

        # Extract date
        date_el = item.select_one(".structItem-startDate time, .structItem-cell--main time")
        post_date_str = None
        if date_el and date_el.get("datetime"):
            post_date_str = date_el["datetime"]

        # Extract question count
        q_count = 0
        q_match = re.search(r"(\d+)\s*(?:câu|cau|questions?)\b", raw_title, re.IGNORECASE)
        if q_match:
            q_count = int(q_match.group(1))
        elif is_fe:
            q_count = 40

        # Extract term
        term_match = re.search(r"\b(SU|FA|SP|WI)\s*(\d{2,4})\b", raw_title, re.IGNORECASE)
        term = None
        if term_match:
            season = term_match.group(1).upper()
            yr_str = term_match.group(2)
            yr_short = yr_str[-2:] if len(yr_str) == 4 else yr_str
            term = f"{season}{yr_short}"

        # Status check: strictly verify docx file exists on disk
        compiled = False
        has_file = False
        missing_file = False
        compiled_at = None
        compiled_at_iso = None
        download_url = None
        db_ex = (db_exams_by_tid.get(tid) if tid else None) or db_exams_by_url.get(norm_url)
        if db_ex:
            from backend.app.modules.export.docx_builder import format_exam_docx_filename
            docx_name = format_exam_docx_filename(subject_code, db_ex)
            docx_path = get_settings().BASE_DIR / "data" / "output" / subject_code / docx_name
            subj_dir = get_settings().BASE_DIR / "data" / "output" / subject_code
            clean_ex_name = re.sub(r"[^a-zA-Z0-9]", "", docx_name.replace(".docx", "")).lower()
            file_found = False
            if docx_path.exists() and docx_path.stat().st_size > 1000:
                file_found = True
            elif subj_dir.exists():
                for p in subj_dir.glob("*.docx"):
                    clean_p = re.sub(r"[^a-zA-Z0-9]", "", p.stem).lower()
                    if clean_ex_name == clean_p and p.stat().st_size > 1000:
                        file_found = True
                        break

            if file_found and db_ex.status == ExamStatus.CRAWLED:
                compiled = True
                has_file = True
                download_url = f"/api/exports/{db_ex.id}/download"
            elif db_ex.status == ExamStatus.CRAWLED and not file_found:
                missing_file = True
                compiled = False
                has_file = False
            else:
                compiled = False
                has_file = False

            dt = db_ex.updated_at or db_ex.created_at
            if dt:
                if dt.tzinfo is None:
                    dt_utc = dt.replace(tzinfo=timezone.utc)
                else:
                    dt_utc = dt.astimezone(timezone.utc)
                compiled_at_iso = dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                compiled_at = compiled_at_iso

            if db_ex:
                real_cnt = await db.scalar(select(func.count(Question.id)).where(Question.exam_id == db_ex.id)) or 0
                if real_cnt > 0:
                    q_count = real_cnt
                elif db_ex.question_count and db_ex.question_count > 0:
                    q_count = db_ex.question_count
                if db_ex.title:
                    cleaned_title = clean_exam_title(db_ex.title)

        results.append({
            "title": cleaned_title or raw_title,
            "url": thread_url,
            "exam_type": exam_type,
            "term": term,
            "post_date": post_date_str,
            "question_count": q_count,
            "compiled": compiled,
            "has_file": has_file,
            "missing_file": missing_file,
            "download_url": download_url,
            "compiled_at": compiled_at,
            "compiled_at_iso": compiled_at_iso,
            "subject_code": subject_code,
        })

    return {"items": results, "total": len(results)}


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

    from backend.app.modules.export.docx_builder import format_exam_docx_filename
    out_dir = get_settings().BASE_DIR / "data" / "output" / clean_code
    exam_outs = []
    for e in sorted_exams:
        docx_name = format_exam_docx_filename(clean_code, e)
        docx_path = out_dir / docx_name
        clean_ex_name = re.sub(r"[^a-zA-Z0-9]", "", docx_name.replace(".docx", "")).lower()
        file_found = False
        if docx_path.exists() and docx_path.stat().st_size > 1000:
            file_found = True
        elif out_dir.exists():
            for p in out_dir.glob("*.docx"):
                clean_p = re.sub(r"[^a-zA-Z0-9]", "", p.stem).lower()
                if clean_ex_name == clean_p and p.stat().st_size > 1000:
                    file_found = True
                    break

        compiled = False
        has_file = False
        missing_file = False
        download_url = None
        compiled_at_iso = None

        if file_found and e.status == ExamStatus.CRAWLED:
            compiled = True
            has_file = True
            download_url = f"/api/exports/{e.id}/download"
        elif e.status == ExamStatus.CRAWLED and not file_found:
            missing_file = True
            compiled = False
            has_file = False
        else:
            compiled = False
            has_file = False

        dt = e.updated_at or e.created_at
        if dt:
            if dt.tzinfo is None:
                dt_utc = dt.replace(tzinfo=timezone.utc)
            else:
                dt_utc = dt.astimezone(timezone.utc)
            compiled_at_iso = dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

        real_q_count = await db.scalar(
            select(func.count(Question.id)).where(Question.exam_id == e.id)
        ) or 0
        final_q_count = real_q_count if real_q_count > 0 else (e.question_count or 0)

        exam_outs.append(
            ExamOut(
                id=e.id,
                subject_id=e.subject_id,
                title=clean_exam_title(e.title),
                url=e.url,
                exam_type=e.exam_type.value if hasattr(e.exam_type, "value") else str(e.exam_type),
                term=e.term,
                post_date=e.post_date,
                question_count=final_q_count,
                compiled=compiled,
                has_file=has_file,
                missing_file=missing_file,
                download_url=download_url,
                compiled_at=compiled_at_iso,
                compiled_at_iso=compiled_at_iso,
            )
        )

    return exam_outs
