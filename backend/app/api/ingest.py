import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.db.models import (
    Answer,
    AnswerStatus,
    Comment,
    Exam,
    ExamStatus,
    ExamType,
    Question,
    QuestionType,
    Subject,
)
from backend.app.db.session import get_db
from backend.app.modules.analysis.ai_check import get_ai_check_service
from backend.app.modules.analysis.voting import tally_votes
from backend.app.modules.export.docx_builder import build_exam_docx
from backend.app.modules.export.image_cropper import crop_exam_images
from backend.app.modules.jobs.orchestrator import compute_doc_settings_hash
from backend.app.modules.settings.service import get_active_settings

logger = get_logger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


class IngestComment(BaseModel):
    comment_id: Optional[str] = None
    author_name: Optional[str] = None
    author_hash: Optional[str] = None
    raw_text: str
    upvotes: int = 0
    quoted_comment_id: Optional[int] = None
    is_reply: bool = False
    posted_at: Optional[str] = None


class IngestQuestion(BaseModel):
    index: int
    file_name: Optional[str] = None
    media_id: Optional[str] = None
    media_url: Optional[str] = None
    image_base64: Optional[str] = None
    comments: List[IngestComment] = Field(default_factory=list)


class IngestExamRequest(BaseModel):
    subject_code: str
    exam_title: str
    exam_url: Optional[str] = None
    term: Optional[str] = None
    exam_type: Optional[str] = "FE"
    questions: List[IngestQuestion]
    options: Optional[Dict[str, Any]] = None


def _verify_ingest_access(request: Request, token: Optional[str] = None) -> None:
    """
    Ensure endpoint is strictly secured:
    1. Host header validation: strictly 127.0.0.1, localhost, or testserver (blocks DNS rebinding).
    2. Origin & Custom Header validation (independent of browser Origin header omission):
       - Extension sends header 'X-DocxStacked-Ext: <EXTENSION_ID>' on all calls.
       - If Origin is present:
           * If Origin == chrome-extension://<EXTENSION_ID>: ALLOW immediately.
           * If Origin is localhost or 127.0.0.1: ALLOW.
           * Any other Origin (external website e.g. evil.com): strictly 403 Forbidden.
       - If Origin is absent/empty (Chrome sidepanel GET, direct extension fetch, or CLI):
           * If 'X-DocxStacked-Ext' matches pinned extension ID: ALLOW immediately.
           * Else: require valid INGEST_TOKEN or return 403 (or 401 if missing token).
    """
    headers = request.headers
    origin_header = (headers.get("origin") or "").strip()
    host_header = (headers.get("host") or "").strip()
    referer_header = (headers.get("referer") or "").strip()
    sec_fetch_site = (headers.get("sec-fetch-site") or "").strip()
    sec_fetch_mode = (headers.get("sec-fetch-mode") or "").strip()
    user_agent = (headers.get("user-agent") or "").strip()
    custom_ext_header = (headers.get("x-docxstacked-ext") or "").strip()

    # Log DEBUG all incoming headers
    method_name = getattr(request, "method", "UNKNOWN")
    path_name = getattr(getattr(request, "url", None), "path", "/api/ingest")
    logger.info(
        f"[INGEST ACCESS] method={method_name} path={path_name} "
        f"Origin='{origin_header}' Host='{host_header}' Referer='{referer_header}' "
        f"Sec-Fetch-Site='{sec_fetch_site}' Sec-Fetch-Mode='{sec_fetch_mode}' "
        f"X-DocxStacked-Ext='{custom_ext_header}' User-Agent='{user_agent[:60]}...'"
    )

    # 1. Host validation against DNS rebinding
    host_name = host_header.split(":")[0].strip().lower()
    allowed_hosts = {"127.0.0.1", "localhost", "testserver"}
    if host_name and host_name not in allowed_hosts:
        logger.warning(f"Rejected ingest request due to invalid Host header: '{host_name}'")
        raise HTTPException(
            status_code=403,
            detail=f"Host '{host_name}' không hợp lệ. Chỉ chấp nhận kết nối tới 127.0.0.1 hoặc localhost.",
        )

    configured_ext_id = (settings.EXTENSION_ID or "kicplcdfmbcfjildbbimpfiljlmfokea").strip()
    valid_ext_origin = f"chrome-extension://{configured_ext_id}"

    # 2. Origin validation
    if origin_header:
        if origin_header.startswith(valid_ext_origin):
            # Trusted extension with pinned ID
            return
        elif origin_header.startswith("http://localhost") or origin_header.startswith("http://127.0.0.1"):
            # Local frontend / dev request
            return
        else:
            logger.warning(f"Unauthorized Origin header in ingest attempt: '{origin_header}'")
            raise HTTPException(
                status_code=403,
                detail=f"Origin '{origin_header}' không được cấp quyền. Chỉ chấp nhận từ extension đã ghim ID hoặc localhost.",
            )

    # 3. If Origin is absent: check custom header X-DocxStacked-Ext matching pinned ID
    if custom_ext_header:
        if custom_ext_header == configured_ext_id:
            # Trusted extension verified via pinned custom header
            return
        else:
            logger.warning(f"Rejected ingest request due to mismatched X-DocxStacked-Ext: '{custom_ext_header}'")
            raise HTTPException(
                status_code=403,
                detail=f"Mã định danh extension '{custom_ext_header}' không khớp với cấu hình server.",
            )

    # 4. Fallback token validation when neither valid Origin nor pinned custom header is provided
    expected_token = (settings.INGEST_TOKEN or "").strip()
    if not expected_token:
        expected_token = getattr(settings, "LOCAL_INGEST_KEY", "docxstacked_local_secret_2026")

    if token and token.strip() == expected_token:
        return

    logger.warning("Rejected ingest request: Missing valid Origin, X-DocxStacked-Ext header, and valid Ingest Token")
    raise HTTPException(
        status_code=403,
        detail="Truy cập bị từ chối. Yêu cầu phải gửi từ extension đã ghim ID hoặc cung cấp Token xác thực hợp lệ.",
    )


@router.get("/ping")
async def ping_ingest(
    request: Request,
    x_ingest_token: Optional[str] = Header(None, alias="X-Ingest-Token"),
    x_local_key: Optional[str] = Header(None, alias="X-Local-Key"),
):
    """
    Lightweight ping endpoint to verify token validity before starting crawl:
    - Returns 200 OK if token matches settings.INGEST_TOKEN.
    - Returns 401 Unauthorized if invalid or missing.
    """
    token = x_ingest_token or x_local_key
    _verify_ingest_access(request, token)
    return {"status": "ok", "message": "Token hợp lệ"}


@router.get("/check-exam")
async def check_exam_exists(
    url: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_ingest_token: Optional[str] = Header(None, alias="X-Ingest-Token"),
    x_local_key: Optional[str] = Header(None, alias="X-Local-Key"),
):
    """
    Check if an exam with the given thread URL has already been compiled in DocxStacked.
    Returns:
      - exists: bool
      - exam_id: Optional[int]
      - compiled_at: Optional[str] (e.g. "14:30 15/11/2026")
      - compiled_time_short: Optional[str] (e.g. "14:30")
      - question_count: int
      - existing_media_ids: List[str]
      - download_url: Optional[str]
    """
    token = x_ingest_token or x_local_key
    _verify_ingest_access(request, token)

    clean_url = url.split("?")[0].rstrip("/") + "/"
    stmt = select(Exam).where(Exam.url == clean_url)
    res = await db.execute(stmt)
    exam = res.scalar_one_or_none()

    if not exam:
        # Also check without trailing slash
        stmt2 = select(Exam).where(Exam.url == clean_url.rstrip("/"))
        res2 = await db.execute(stmt2)
        exam = res2.scalar_one_or_none()

    if not exam:
        return {"exists": False}

    # Query questions to get count and existing media_ids
    q_stmt = select(Question).where(Question.exam_id == exam.id).order_by(Question.index)
    q_res = await db.execute(q_stmt)
    questions = q_res.scalars().all()

    existing_media_ids = [q.media_id for q in questions if q.media_id and q.local_image_path]

    # Read sidecar meta if exists
    meta_path = settings.DATA_DIR / "output"
    compiled_dt = exam.updated_at or exam.created_at
    if compiled_dt:
        if compiled_dt.tzinfo is None:
            compiled_utc = compiled_dt.replace(tzinfo=timezone.utc)
        else:
            compiled_utc = compiled_dt.astimezone(timezone.utc)
        compiled_iso_utc = compiled_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        compiled_formatted = compiled_dt.strftime("%H:%M %d/%m/%Y")
        compiled_time_short = compiled_dt.strftime("%H:%M")
    else:
        compiled_iso_utc = None
        compiled_formatted = ""
        compiled_time_short = ""

    # Query subject code to return string rather than subject_id
    subj_code = ""
    if exam.subject_id:
        s_obj = await db.get(Subject, exam.subject_id)
        if s_obj:
            subj_code = s_obj.code

    return {
        "exists": True,
        "exam_id": exam.id,
        "subject_code": subj_code or str(exam.subject_id),  # Real subject code e.g. MLN122
        "title": exam.title,
        "compiled_at": compiled_iso_utc or compiled_formatted,
        "compiled_at_iso": compiled_iso_utc,
        "compiled_time_short": compiled_time_short,
        "question_count": len(questions),
        "existing_media_ids": existing_media_ids,
        "download_url": f"/api/exports/{exam.id}/download",
    }


async def _run_background_ai_refinement(
    exam_id: int,
    subject_code: str,
    active_cfg: Dict[str, Any],
    opt_cfg: Dict[str, Any],
    cropped_dir: Path,
):
    """
    Run AI refinement asynchronously in background:
    - Queries AI for uncertain questions without blocking the HTTP ingest response.
    - Updates answers in database.
    - Re-exports Word docx with AI enhancements.
    """
    from backend.app.db.session import async_session_factory
    from backend.app.db.models import Exam, Question, Answer

    ai_service = get_ai_check_service()
    if not ai_service.is_available():
        return

    ai_weight = float(active_cfg.get("voting", {}).get("ai_weight", 1.0))
    max_opt_letter = active_cfg.get("voting", {}).get("max_option_letter", "H")
    ai_mode = active_cfg.get("ai", {}).get("mode", "only_uncertain")

    try:
        async with async_session_factory() as db:
            e_res = await db.execute(select(Exam).where(Exam.id == exam_id))
            exam = e_res.scalar_one_or_none()
            if not exam:
                return

            q_res = await db.execute(select(Question).where(Question.exam_id == exam_id).order_by(Question.index))
            db_questions = q_res.scalars().all()

            updated_any = False
            answers_map: Dict[int, Answer] = {}

            for q_obj in db_questions:
                await db.refresh(q_obj, ["comments", "answer"])
                need_ai = False
                has_missing_options = "missing_options" in (q_obj.crop_warnings or [])
                if not has_missing_options and ai_service.is_available():
                    if ai_mode == "all":
                        need_ai = True
                    elif ai_mode == "off":
                        need_ai = False
                    else:
                        if not q_obj.answer or q_obj.answer.status in (AnswerStatus.CONFLICT, AnswerStatus.WEAK, AnswerStatus.NO_DATA) or q_obj.answer.confidence < 0.80:
                            need_ai = True

                ai_votes = []
                ai_options = {}
                img_path = getattr(q_obj, "cropped_image_path", None) or getattr(q_obj, "local_image_path", None)
                if need_ai and img_path and ai_service.is_available():
                    local_img = Path(img_path) if Path(img_path).is_absolute() else settings.BASE_DIR / img_path
                    if local_img.exists():
                        analyses = ai_service.analyze_question_ensemble(local_img)
                        for a in analyses:
                            ai_votes.append({
                                "provider": a.provider or "ai",
                                "answers": a.answers,
                                "confidence": a.confidence,
                            })
                            if a.options:
                                ai_options.update(a.options)

                voting_res = tally_votes(
                    q_obj.comments,
                    ai_votes=ai_votes if ai_votes else None,
                    ai_weight=ai_weight,
                    max_option_letter=max_opt_letter,
                )

                breakdown = dict(voting_res.vote_breakdown)
                if ai_options:
                    breakdown["_options"] = ai_options
                if ai_votes:
                    breakdown["_ai_votes"] = ai_votes
                    updated_any = True
                elif need_ai and not ai_service.is_available():
                    breakdown["ai_pending"] = True

                if not q_obj.answer:
                    ans = Answer(
                        question_id=q_obj.id,
                        answer_set=voting_res.answer_set,
                        status=voting_res.status,
                        confidence=voting_res.confidence,
                        valid_comments_count=voting_res.voters_count,
                        vote_breakdown=breakdown,
                    )
                    db.add(ans)
                    q_obj.answer = ans
                else:
                    q_obj.answer.answer_set = voting_res.answer_set
                    q_obj.answer.status = voting_res.status
                    q_obj.answer.confidence = voting_res.confidence
                    q_obj.answer.valid_comments_count = voting_res.voters_count
                    q_obj.answer.vote_breakdown = breakdown

                answers_map[q_obj.id] = q_obj.answer

            await db.commit()

            if updated_any:
                ans_format = opt_cfg.get("answer_format", active_cfg.get("export", {}).get("answer_format", "letter_keyword"))
                multi_choice_fmt = opt_cfg.get("multi_choice_format", active_cfg.get("export", {}).get("multi_choice_format", "comma"))
                highlight_check_needed = active_cfg.get("export", {}).get("highlight_low_confidence", True)
                add_divider = active_cfg.get("export", {}).get("show_separator_line", True)
                add_question_number = active_cfg.get("export", {}).get("show_question_number", True)

                build_exam_docx(
                    subject_code=subject_code,
                    exam=exam,
                    questions=db_questions,
                    cropped_dir=cropped_dir,
                    answers_map=answers_map,
                    answer_format=ans_format,
                    multi_choice_format=multi_choice_fmt,
                    highlight_check_needed=highlight_check_needed,
                    add_divider=add_divider,
                    add_question_number=add_question_number,
                )
                logger.info(f"Background AI refinement completed and updated Word document for exam {exam_id}.")
    except Exception as bg_err:
        logger.warning(f"Background AI refinement encountered error: {bg_err}")


@router.post("")
async def ingest_exam(
    request: Request,
    payload: IngestExamRequest,
    background_tasks: BackgroundTasks,
    x_ingest_token: Optional[str] = Header(None, alias="X-Ingest-Token"),
    x_local_key: Optional[str] = Header(None, alias="X-Local-Key"),
    content_length: Optional[int] = Header(None, alias="Content-Length"),
    db: AsyncSession = Depends(get_db),
):
    """
    Ingest exam data from Chromium browser extension:
    - Strictly verifies Origin header & Token.
    - Limits payload size (default 100MB max).
    - Preserves existing exam title if already present in database (no title rewriting).
    - Saves raw images & comments.
    - Automatically executes cropping, voting & AI analysis (without crawling).
    - Generates standard Word (.docx) document ready for download.
    """
    # 0. Check payload size
    max_bytes = getattr(settings, "MAX_INGEST_PAYLOAD_BYTES", 100 * 1024 * 1024)
    if content_length and content_length > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Kích thước tải lên ({content_length / 1024 / 1024:.1f} MB) vượt quá giới hạn cho phép ({max_bytes / 1024 / 1024:.0f} MB).",
        )

    # 1. Security verification (Origin + Token)
    token = x_ingest_token or x_local_key
    _verify_ingest_access(request, token)

    # Save debug payload copy to data/ingest_debug/
    try:
        debug_dir = settings.DATA_DIR / "ingest_debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_sub = re.sub(r"[^\w\-]", "_", payload.subject_code)
        debug_file = debug_dir / f"payload_{safe_sub}_{timestamp_str}.json"
        with open(debug_file, "w", encoding="utf-8") as f:
            json.dump(payload.model_dump(), f, ensure_ascii=False, indent=2)
        logger.info(f"Saved ingest debug payload to {debug_file}")
    except Exception as e:
        logger.warning(f"Could not save debug ingest payload: {e}")

    code = payload.subject_code.upper().strip()
    incoming_title = payload.exam_title.strip()

    # 1. Get or create Subject
    stmt = select(Subject).where(Subject.code == code)
    res = await db.execute(stmt)
    subject = res.scalar_one_or_none()
    if not subject:
        subject = Subject(
            code=code,
            name=f"Môn {code}",
            forum_url=f"https://fuoverflow.com/forums/{code}/",
        )
        db.add(subject)
        await db.flush()

    # 2. Extract term & exam_type
    term = payload.term
    if not term:
        m_term = re.search(r"\b(SU|FA|SP|WI)\d{2}\b", incoming_title, re.IGNORECASE)
        term = m_term.group(0).upper() if m_term else "SU26"

    e_type_str = (payload.exam_type or "FE").upper()
    e_type = ExamType.PE if "PE" in e_type_str else ExamType.FE

    # 3. Get or create Exam - PRESERVE existing title if exam already exists
    exam_url = payload.exam_url or f"https://fuoverflow.com/threads/{re.sub(r'[^a-zA-Z0-9]', '-', incoming_title.lower())}/"
    if exam_url:
        stmt = select(Exam).where(Exam.url == exam_url)
    else:
        stmt = select(Exam).where(Exam.subject_id == subject.id, Exam.title == incoming_title)
    res = await db.execute(stmt)
    exam = res.scalar_one_or_none()
    if not exam:
        # Clean title: don't duplicate subject code, remove any trailing suffixes
        clean_title = incoming_title
        exam = Exam(
            subject_id=subject.id,
            title=clean_title,
            term=term,
            exam_type=e_type,
            url=exam_url,
            question_count=len(payload.questions),
            status=ExamStatus.CRAWLED,
        )
        db.add(exam)
        await db.flush()
    else:
        # Requirement: Do NOT change title of existing exam. Keep original exam.title!
        logger.info(f"Exam already exists (ID={exam.id}). Preserving original title: '{exam.title}'")
        exam.term = exam.term or term
        exam.exam_type = exam.exam_type or e_type
        exam.question_count = len(payload.questions)
        exam.status = ExamStatus.CRAWLED
        await db.flush()

    # Clean up display title: if incoming_title already begins with code, avoid duplicating
    clean_display_title = exam.title
    if clean_display_title.upper().startswith(f"{code} - "):
        display_str = clean_display_title
    else:
        display_str = f"{code} - {clean_display_title}"
    logger.info(f"Ingesting exam from extension: {display_str} ({len(payload.questions)} questions)")

    # 4. Prepare raw image storage directory
    exam_slug = re.sub(r"[^\w\-]", "_", f"exam_{exam.id}_{term.lower()}")
    exam_raw_dir = settings.STORAGE_DIR / "raw" / code / exam_slug
    exam_raw_dir.mkdir(parents=True, exist_ok=True)

    # 5. Process Questions & Comments
    db_questions: List[Question] = []
    total_comments_saved = 0

    for q_data in payload.questions:
        idx = q_data.index
        file_name = q_data.file_name or f"Q{idx}.webp"
        local_img_filename = f"q{idx:02d}_{file_name}"
        local_img_path = exam_raw_dir / local_img_filename

        # Decode base64 image if provided
        if q_data.image_base64:
            b64_str = q_data.image_base64
            if "," in b64_str:
                b64_str = b64_str.split(",", 1)[1]
            try:
                img_bytes = base64.b64decode(b64_str)
                local_img_path.write_bytes(img_bytes)
            except Exception as b64_err:
                logger.warning(f"Error decoding image for Q{idx}: {b64_err}")

        rel_img_path = (
            str(local_img_path.resolve().relative_to(settings.BASE_DIR.resolve())).replace("\\", "/")
            if local_img_path.exists()
            else None
        )

        # Upsert Question
        stmt = select(Question).where(Question.exam_id == exam.id, Question.index == idx)
        res = await db.execute(stmt)
        q_obj = res.scalar_one_or_none()

        if not q_obj:
            q_obj = Question(
                exam_id=exam.id,
                index=idx,
                file_name=file_name,
                local_image_path=rel_img_path,
                media_url=q_data.media_url,
                media_id=q_data.media_id,
            )
            db.add(q_obj)
            await db.flush()
        else:
            q_obj.file_name = file_name
            if rel_img_path:
                q_obj.local_image_path = rel_img_path
            q_obj.media_url = q_data.media_url
            q_obj.media_id = q_data.media_id

        # Save Comments
        # Clear existing comments for this question if re-ingesting
        existing_comms_stmt = select(Comment).where(Comment.question_id == q_obj.id)
        ex_res = await db.execute(existing_comms_stmt)
        for old_c in ex_res.scalars().all():
            await db.delete(old_c)

        for c_idx, c_data in enumerate(q_data.comments):
            raw_text = c_data.raw_text.strip()
            if not raw_text:
                continue

            if c_data.author_hash:
                author = c_data.author_hash
            elif c_data.author_name and c_data.author_name.strip() and c_data.author_name.strip().lower() != "unknown":
                author = hashlib.sha256(c_data.author_name.strip().encode("utf-8")).hexdigest()[:16]
            elif c_data.comment_id:
                author = f"anon_c_{c_data.comment_id}"
            else:
                author = f"anon_q{idx}_{c_idx}"

            parsed_posted_at = None
            if c_data.posted_at:
                try:
                    if isinstance(c_data.posted_at, datetime):
                        parsed_posted_at = c_data.posted_at
                    else:
                        parsed_posted_at = datetime.fromisoformat(str(c_data.posted_at).strip())
                except Exception:
                    parsed_posted_at = None

            comm_obj = Comment(
                question_id=q_obj.id,
                comment_id=c_data.comment_id or str(idx),
                author_hash=author,
                raw_text=raw_text,
                upvotes=c_data.upvotes,
                quoted_comment_id=c_data.quoted_comment_id,
                is_reply=c_data.is_reply,
                posted_at=parsed_posted_at,
            )
            db.add(comm_obj)
            total_comments_saved += 1

        db_questions.append(q_obj)

    await db.commit()

    # 6. Automatic Cropping Layout Engine
    cropped_dir = settings.STORAGE_DIR / "cropped" / code / f"exam_{exam.id}"
    crop_summary = crop_exam_images(
        exam_id=exam.id,
        exam_title=exam.title,
        questions=db_questions,
        cropped_dir=cropped_dir,
    )
    exam.crop_layout = crop_summary.dominant_layout
    for q_obj, crop_res in zip(db_questions, crop_summary.results):
        q_obj.crop_layout = crop_res.layout
        q_obj.crop_warnings = crop_res.warnings
        if crop_res.output_path:
            q_obj.cropped_image_path = str(crop_res.output_path)
        if crop_res.choice_hint_path:
            q_obj.choice_hint_path = str(crop_res.choice_hint_path)
        q_obj.choice_hint_width_px = crop_res.choice_hint_width_px
    await db.commit()

    # 7. Tally Community Votes immediately (Fast response for user)
    # AI refinement is scheduled in background to keep response time fast
    active_cfg = await get_active_settings(db)
    opt_cfg = payload.options or {}
    ai_enabled = opt_cfg.get("ai_enabled", active_cfg.get("ai", {}).get("enabled", True))
    ai_weight = float(active_cfg.get("voting", {}).get("ai_weight", 1.0))
    max_opt_letter = active_cfg.get("voting", {}).get("max_option_letter", "H")
    ai_service = get_ai_check_service()

    answers_map: Dict[int, Answer] = {}
    for q_obj in db_questions:
        await db.refresh(q_obj, ["comments", "answer"])

        voting_res = tally_votes(
            q_obj.comments,
            ai_weight=ai_weight,
            max_option_letter=max_opt_letter,
        )

        breakdown = dict(voting_res.vote_breakdown)
        if ai_enabled and (voting_res.status in (AnswerStatus.CONFLICT, AnswerStatus.WEAK, AnswerStatus.NO_DATA) or voting_res.confidence < 0.80):
            breakdown["ai_pending"] = True

        if not q_obj.answer:
            ans = Answer(
                question_id=q_obj.id,
                answer_set=voting_res.answer_set,
                status=voting_res.status,
                confidence=voting_res.confidence,
                valid_comments_count=voting_res.voters_count,
                vote_breakdown=breakdown,
            )
            db.add(ans)
            q_obj.answer = ans
        else:
            q_obj.answer.answer_set = voting_res.answer_set
            q_obj.answer.status = voting_res.status
            q_obj.answer.confidence = voting_res.confidence
            q_obj.answer.valid_comments_count = voting_res.voters_count
            q_obj.answer.vote_breakdown = breakdown

        answers_map[q_obj.id] = q_obj.answer

    await db.commit()

    # Schedule background AI refinement if AI is enabled and service is available
    if ai_enabled and ai_service.is_available():
        background_tasks.add_task(
            _run_background_ai_refinement,
            exam_id=exam.id,
            subject_code=code,
            active_cfg=active_cfg,
            opt_cfg=opt_cfg,
            cropped_dir=cropped_dir,
        )

    # 8. Word Document Generation (Aligned with orchestrator)
    ans_format = opt_cfg.get("answer_format", active_cfg.get("export", {}).get("answer_format", "letter_keyword"))
    multi_choice_fmt = opt_cfg.get("multi_choice_format", active_cfg.get("export", {}).get("multi_choice_format", "comma"))
    highlight_check_needed = active_cfg.get("export", {}).get("highlight_low_confidence", True)
    add_divider = active_cfg.get("export", {}).get("show_separator_line", True)
    add_question_number = active_cfg.get("export", {}).get("show_question_number", True)

    docx_path = build_exam_docx(
        subject_code=code,
        exam=exam,
        questions=db_questions,
        cropped_dir=cropped_dir,
        answers_map=answers_map,
        answer_format=ans_format,
        multi_choice_format=multi_choice_fmt,
        highlight_check_needed=highlight_check_needed,
        add_divider=add_divider,
        add_question_number=add_question_number,
        unsupported_layout_warning=crop_summary.fallback_to_raw,
        use_raw_fallback=crop_summary.fallback_to_raw,
    )

    # Save sidecar metadata
    now_dt = datetime.now()
    meta_data = {
        "settings_hash": compute_doc_settings_hash(active_cfg),
        "created_at": now_dt.isoformat(),
        "created_at_epoch": now_dt.timestamp(),
        "created_at_formatted": now_dt.strftime("%H:%M %d/%m/%Y"),
        "latest_comment_timestamp": now_dt.timestamp(),
        "questions_count": len(db_questions),
        "exam_title": exam.title,
    }
    meta_path = docx_path.with_name(docx_path.name + ".meta.json")
    meta_path.write_text(json.dumps(meta_data, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info(f"Ingest completed successfully: {docx_path} ({docx_path.stat().st_size} bytes)")

    return {
        "status": "success",
        "exam_id": exam.id,
        "subject_code": code,
        "exam_title": exam.title,
        "questions_ingested": len(db_questions),
        "comments_ingested": total_comments_saved,
        "docx_filename": docx_path.name,
        "docx_path": str(docx_path),
        "download_url": f"/api/exports/{exam.id}/download",
    }


class PEChunkUploadRequest(BaseModel):
    subject_code: str
    exam_title: str
    file_name: str
    chunk_index: int
    total_chunks: int
    chunk_base64: str


@router.post("/pe-upload-chunk")
async def upload_pe_chunk(
    payload: PEChunkUploadRequest,
    request: Request,
    x_ingest_token: Optional[str] = Header(None, alias="X-Ingest-Token"),
    x_local_key: Optional[str] = Header(None, alias="X-Local-Key"),
):
    """
    Upload large PE files in chunks (approx 8MB per chunk).
    Reassembles into data/output/{SUBJECT}/{SUBJECT}_PE/{ExamTitle}/{file_name}.
    """
    token = x_ingest_token or x_local_key
    _verify_ingest_access(request, token)

    subj = payload.subject_code.upper().strip()
    clean_title = re.sub(r'[\\/*?:"<>|]', '', payload.exam_title).strip()
    safe_filename = Path(payload.file_name).name

    target_dir = settings.OUTPUT_DIR / subj / f"{subj}_PE" / clean_title
    target_dir.mkdir(parents=True, exist_ok=True)

    temp_chunk_dir = settings.STORAGE_DIR / "cache" / "pe_chunks" / f"{subj}_{clean_title}_{safe_filename}"
    temp_chunk_dir.mkdir(parents=True, exist_ok=True)

    chunk_file = temp_chunk_dir / f"chunk_{payload.chunk_index:05d}.bin"
    raw_b64 = payload.chunk_base64
    if "," in raw_b64:
        raw_b64 = raw_b64.split(",", 1)[1]
    # Handle padding if needed
    missing_padding = len(raw_b64) % 4
    if missing_padding:
        raw_b64 += "=" * (4 - missing_padding)
    chunk_bytes = base64.b64decode(raw_b64)
    chunk_file.write_bytes(chunk_bytes)

    # Check if all chunks have been received
    received = list(temp_chunk_dir.glob("chunk_*.bin"))
    if len(received) >= payload.total_chunks:
        final_file = target_dir / safe_filename
        with open(final_file, "wb") as outfile:
            for idx in range(payload.total_chunks):
                cf = temp_chunk_dir / f"chunk_{idx:05d}.bin"
                if not cf.exists():
                    raise HTTPException(status_code=400, detail=f"Missing chunk {idx}")
                outfile.write(cf.read_bytes())

        # Cleanup chunk dir
        import shutil
        shutil.rmtree(temp_chunk_dir, ignore_errors=True)

        logger.info(f"PE file successfully reassembled: {final_file} ({final_file.stat().st_size} bytes)")
        return {
            "status": "completed",
            "file_name": safe_filename,
            "size_bytes": final_file.stat().st_size,
            "saved_path": str(final_file.relative_to(settings.BASE_DIR)).replace("\\", "/"),
        }

    return {
        "status": "chunk_received",
        "chunk_index": payload.chunk_index,
        "chunks_received": len(received),
        "total_chunks": payload.total_chunks,
    }

