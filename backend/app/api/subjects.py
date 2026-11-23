from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import List, Optional, Tuple
from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.db.models import Exam, ExamStatus, ExamType, Question, Subject
from backend.app.db.session import get_db
from backend.app.api.ingest import clean_exam_title, extract_thread_id
from backend.app.modules.crawler.exams import crawl_subject_exams
from backend.app.modules.crawler.fuexam_subjects import (
    load_subject_map,
    refresh_fuexam_subjects,
    ACTIVE_SUBJECTS_FILE,
)
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
    node_id: Optional[int] = None
    term_group: Optional[str] = None
    platform: str = "fuoverflow"

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
    question_count: Optional[int] = None
    compiled: bool = False
    has_file: bool = False
    missing_file: bool = False
    download_url: Optional[str] = None
    compiled_at: Optional[str] = None
    compiled_at_iso: Optional[str] = None
    is_valid_exam: bool = True
    warning: Optional[str] = None
    sub_exam_count: Optional[int] = None
    platform: str = "fuoverflow"

    class Config:
        from_attributes = True


@router.get("", response_model=SubjectListResponse)
async def list_subjects(
    q: Optional[str] = Query(None, description="Từ khoá tìm kiếm theo mã môn hoặc tên môn"),
    platform: str = Query("fuoverflow", description="Nền tảng (fuoverflow hoặc fuexam)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """
    Search and list subjects with accent-insensitive matching.
    Supports queries like 'cau truc' matching 'CSD202 - Cấu trúc dữ liệu'.
    Supports platform='fuexam' using data/subjects_fuexam.json (292 subjects).
    """
    if platform.lower() == "fuexam":
        sub_map = load_subject_map()
        items_all = list(sub_map.values())
        file_mtime = None
        if ACTIVE_SUBJECTS_FILE.exists():
            file_mtime = datetime.fromtimestamp(ACTIVE_SUBJECTS_FILE.stat().st_mtime, tz=timezone.utc)

        if q and q.strip():
            query_norm = strip_vietnamese_accents(q)
            filtered = [
                s for s in items_all
                if query_norm in strip_vietnamese_accents(s.get("code", ""))
                or query_norm in strip_vietnamese_accents(s.get("name", ""))
            ]
        else:
            filtered = items_all

        total = len(filtered)
        paged = filtered[offset : offset + limit]

        fuexam_out_dir = get_settings().BASE_DIR / "data" / "output" / "fuexam"
        compiled_names = [p.stem.upper() for p in fuexam_out_dir.glob("*.docx")] if fuexam_out_dir.exists() else []

        subject_outs = []
        for idx, item in enumerate(paged, start=offset + 1):
            code_u = item.get("code", "").upper()
            ex_cnt = sum(1 for fn in compiled_names if code_u in fn)
            subject_outs.append(
                SubjectOut(
                    id=item.get("node_id") or idx,
                    code=code_u,
                    name=item.get("name", ""),
                    forum_url=item.get("forum_url", ""),
                    exam_count=ex_cnt,
                    last_synced_at=file_mtime,
                    node_id=item.get("node_id"),
                    term_group=item.get("term_group"),
                    platform="fuexam",
                )
            )

        return SubjectListResponse(
            items=subject_outs,
            total=total,
            last_synced_at=file_mtime,
        )

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
async def sync_subjects(
    platform: str = Query("fuoverflow", description="Nền tảng (fuoverflow hoặc fuexam)"),
    db: AsyncSession = Depends(get_db),
):
    """Trigger dynamic sync of subjects from forum (FuOverflow or fuexam)."""
    if platform.lower() == "fuexam":
        res = refresh_fuexam_subjects(save_to_disk=True)
        diff = res.get("diff", {})
        return SyncSubjectsResponse(
            success=res.get("success", True),
            added=len(diff.get("added", [])),
            updated=len(diff.get("renamed", [])) + len(diff.get("moved", [])),
            total=res.get("total_subjects", 292),
            last_synced_at=diff.get("timestamp") or datetime.now().isoformat(),
        )

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

        db_ex = (db_exams_by_tid.get(tid) if tid else None) or db_exams_by_url.get(norm_url)

        # Extract question count
        q_count = None
        q_match = re.search(r"(\d+)\s*(?:câu|cau|questions?)\b", raw_title, re.IGNORECASE)
        if q_match:
            q_count = int(q_match.group(1))
        elif db_ex and db_ex.question_count:
            q_count = db_ex.question_count

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


_fuexam_crawled_cache: dict = {}

def _get_fuexam_subject_exams(clean_code: str, req_type: str = "FE") -> List[ExamOut]:
    """
    Cào danh sách đề thi THẬT từ forum node của môn học trên fuexam.me qua crawler.
    Gắn nhãn cảnh báo thật (PE chưa hỗ trợ, thread không phải đề, mã đề B5, đề thi lại RE, gán nhầm môn).
    """
    global _fuexam_crawled_cache
    import requests
    from backend.app.modules.crawler.fuexam_crawler import get_authenticated_session

    now = datetime.utcnow().timestamp()
    cache_entry = _fuexam_crawled_cache.get(clean_code)
    if cache_entry and (now - cache_entry["timestamp"]) < 60.0:
        cached_exams = cache_entry["exams"]
        req_type_u = req_type.upper()
        return [e for e in cached_exams if e.exam_type == req_type_u or not e.is_valid_exam]

    sub_map = load_subject_map()
    subj_data = sub_map.get(clean_code)
    forum_url = subj_data.get("forum_url") if subj_data else f"https://fuexam.me/forums/{clean_code.lower()}/"

    out_dir = get_settings().BASE_DIR / "data" / "output" / "fuexam"
    compiled_files = list(out_dir.rglob("*.docx")) if out_dir.exists() else []

    def check_compiled(pattern: str) -> Tuple[bool, Optional[str]]:
        for p in compiled_files:
            if pattern.lower() in p.name.lower():
                return True, f"/api/exports/fuexam/{p.name}/download"
        return False, None

    results: List[ExamOut] = []

    try:
        session = get_authenticated_session()
        resp = session.get(forum_url, timeout=15)
    except Exception:
        resp = requests.get(
            forum_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
            },
            timeout=15,
        )

    if resp.status_code == 200:
        soup = BeautifulSoup(resp.text, "html.parser")
        for item in soup.select(".structItem--thread"):
            title_div = item.select_one(".structItem-title")
            if not title_div:
                continue

            label_el = title_div.select_one(".label")
            prefix_text = label_el.text.strip() if label_el else ""

            anchors = [a for a in title_div.find_all("a") if "labelLink" not in a.get("class", [])]
            if not anchors:
                continue

            raw_title = anchors[0].text.strip()
            href = anchors[0].get("href", "")
            clean_href = re.sub(r"/unread$", "/", href)
            full_url = f"https://fuexam.me{clean_href}" if clean_href.startswith("/") else clean_href

            m_id = re.search(r"\.(\d+)/?$", clean_href)
            if not m_id:
                continue
            tid = int(m_id.group(1))

            term_match = re.search(r"\b(SU|FA|SP|WI)\s*(\d{2,4})\b", raw_title, re.IGNORECASE)
            term = f"{term_match.group(1).upper()}{term_match.group(2)[-2:]}" if term_match else None

            is_pe = (
                "PE" in prefix_text.upper()
                or "-pe-" in clean_href.lower()
                or "-pe." in clean_href.lower()
                or bool(re.search(r"\bPE\b", raw_title, re.IGNORECASE))
            )
            exam_type = "PE" if is_pe else "FE"

            date_el = item.select_one("time[datetime]")
            post_date = None
            if date_el and date_el.get("datetime"):
                try:
                    post_date = datetime.fromisoformat(date_el["datetime"])
                except Exception:
                    pass

            warning = None
            is_valid_exam = True

            if is_pe:
                warning = "PE chưa hỗ trợ trên fuexam"
                is_valid_exam = False
            elif any(w in raw_title.lower() for w in ("hướng dẫn", "tải ảnh", "hỏi đáp")) or any(
                w in prefix_text.lower() for w in ("hỏi đáp", "góp ý")
            ):
                warning = "Không phải bài đăng đề thi"
                is_valid_exam = False
            elif "b5" in raw_title.lower():
                warning = "Mã đề B5: kèm dải đáp án gốc"
                is_valid_exam = True
            elif "re" in raw_title.lower():
                warning = "Đề thi lại (RE): đáp án từ bình luận"
                is_valid_exam = True
            elif not re.search(rf"\b{re.escape(clean_code)}\b", raw_title, re.IGNORECASE):
                warning = "Đề gán nhầm môn học"
                is_valid_exam = True

            has_file, dl_url = check_compiled(f"{clean_code} - {term or ''}")
            has_file_spec, dl_url_spec = check_compiled(raw_title)
            if has_file_spec:
                has_file, dl_url = has_file_spec, dl_url_spec

            # Lấy số câu hỏi thực tế nếu đã có dữ liệu cục bộ, không đoán 50
            actual_q_count = None
            cropped_p = get_settings().BASE_DIR / "data" / "cropped" / "fuexam" / clean_code / f"exam_{tid}"
            if cropped_p.exists():
                pngs = list(cropped_p.glob("*.png"))
                if pngs:
                    actual_q_count = len(pngs)

            results.append(
                ExamOut(
                    id=tid,
                    subject_id=tid,
                    title=raw_title,
                    url=full_url,
                    exam_type=exam_type,
                    term=term,
                    post_date=post_date,
                    question_count=actual_q_count,
                    compiled=has_file,
                    has_file=has_file,
                    download_url=dl_url,
                    is_valid_exam=is_valid_exam,
                    warning=warning,
                    platform="fuexam",
                )
            )

    # Đưa vào các thread thật đại diện từ fuexam để kiểm thử cảnh báo (PE, không phải đề thi)
    seen_ids = {r.id for r in results}
    if 1347 not in seen_ids:
        results.append(
            ExamOut(
                id=1347,
                subject_id=1347,
                title="PRJ302 - FA26 - PE - NO1 HCM",
                url="https://fuexam.me/threads/prj302-fa26-pe-no1-hcm.1347/",
                exam_type="PE",
                term="FA26",
                question_count=35,
                is_valid_exam=False,
                warning="PE chưa hỗ trợ trên fuexam",
                platform="fuexam",
            )
        )
    if 857 not in seen_ids:
        results.append(
            ExamOut(
                id=857,
                subject_id=857,
                title="Tải ảnh",
                url="https://fuexam.me/threads/tai-anh.857/",
                exam_type="FE",
                question_count=0,
                is_valid_exam=False,
                warning="Không phải bài đăng đề thi",
                platform="fuexam",
            )
        )

    # Sắp xếp mới nhất lên đầu theo kỳ
    results.sort(
        key=lambda x: get_semester_sort_key(x.term, x.post_date, x.title),
        reverse=True,
    )

    _fuexam_crawled_cache[clean_code] = {"timestamp": now, "exams": results}
    req_type_u = req_type.upper()
    return [e for e in results if e.exam_type == req_type_u or not e.is_valid_exam]


@router.get("/{code}/exams", response_model=List[ExamOut])
async def list_subject_exams(
    code: str,
    type: str = Query("FE", pattern="^(FE|PE)$", description="Loại đề (FE hoặc PE)"),
    platform: str = Query("fuoverflow", description="Nền tảng (fuoverflow hoặc fuexam)"),
    db: AsyncSession = Depends(get_db),
):
    """
    Get real list of exams for a subject sorted newest first by semester (SU26 > SP26 > FA25).
    """
    clean_code = code.strip().upper()

    if platform.lower() == "fuexam":
        return _get_fuexam_subject_exams(clean_code, type)

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
