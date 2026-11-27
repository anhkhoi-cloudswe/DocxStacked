import asyncio
import hashlib
import json
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.db.models import Answer, AnswerStatus, Comment, Exam, ExamType, Job, JobStatus, Question, Subject
from backend.app.db.session import async_session_factory
from backend.app.modules.analysis.ai_check import get_ai_check_service
from backend.app.modules.analysis.voting import tally_votes
from backend.app.modules.settings.service import get_active_settings
from backend.app.modules.crawler.browser import AuthenticationRequiredError, get_browser_manager, run_in_browser_thread
from backend.app.modules.crawler.comments import crawl_exam_comments
from backend.app.modules.crawler.exams import crawl_subject_exams
from backend.app.modules.crawler.questions import crawl_exam_questions
from backend.app.modules.crawler.subjects import get_or_fetch_subjects
from backend.app.modules.export.docx_builder import build_exam_docx, build_merged_docx, format_exam_docx_filename, normalize_term
from backend.app.modules.export.image_cropper import crop_exam_images, CROP_ALGORITHM_VERSION
from backend.app.storage.local import LocalStorage

logger = get_logger(__name__)
settings = get_settings()


def compute_doc_settings_hash(config_snapshot: Dict[str, Any]) -> str:
    """
    Compute a deterministically sorted hash of settings that affect the generated Word doc:
    answer_format, image_width_cm, zoom_percent, highlight_low_confidence, show_question_number,
    show_separator_line, ai_enabled.
    """
    export_cfg = config_snapshot.get("export", {})
    ai_cfg = config_snapshot.get("ai", {})
    key_data = {
        "answer_format": export_cfg.get("answer_format", "letter_keyword"),
        "multi_choice_format": export_cfg.get("multi_choice_format", "comma"),
        "image_width_cm": float(export_cfg.get("image_width_cm", 16.51)),
        "image_zoom_percent": int(export_cfg.get("image_zoom_percent", 100)),
        "highlight_low_confidence": bool(export_cfg.get("highlight_low_confidence", True)),
        "show_question_number": bool(export_cfg.get("show_question_number", True)),
        "show_separator_line": bool(export_cfg.get("show_separator_line", True)),
        "ai_enabled": bool(ai_cfg.get("enabled", True)),
        "crop_algorithm_version": CROP_ALGORITHM_VERSION,
    }
    return hashlib.sha256(json.dumps(key_data, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def classify_job_error(e: Exception) -> tuple[str, str, bool]:
    """
    Classify error into (user_friendly_message, error_code, is_retryable).
    Never exposes raw internal tracebacks to the user.
    """
    err_str = str(e)
    err_cls = e.__class__.__name__

    # 1. Auth errors
    if "AuthenticationRequiredError" in err_cls or "FuexamAuthError" in err_cls or any(
        k in err_str.lower() for k in ["hết hạn", "chính sách 1 phiên", "đăng nhập lại", "cần đăng nhập", "phiên đăng nhập"]
    ):
        return err_str, "AUTH_REQUIRED", True

    # 2. Network / connection / timeout errors (giữ nguyên mã NET-xxxxxx nếu đã có)
    existing_code = getattr(e, "error_code", None)
    if existing_code and isinstance(existing_code, str) and existing_code.startswith("NET-"):
        return f"{err_str} (Mã lỗi: {existing_code})", existing_code, True

    if isinstance(e, (asyncio.TimeoutError, ConnectionError, OSError)) or any(
        k in err_cls.lower() for k in ["timeout", "connection", "network"]
    ) or any(
        k in err_str.lower() for k in [
            "timeout", "timed out", "kết nối mạng", "connection reset",
            "connection refused", "failed to establish", "ngắt kết nối"
        ]
    ):
        code = f"NET-{uuid.uuid4().hex[:6].upper()}"
        return f"Lỗi kết nối mạng khi tải dữ liệu, vui lòng kiểm tra kết nối và thử lại. (Mã lỗi: {code})", code, True

    # 3. Known domain validation errors (user actionable or data input errors)
    known_validation_prefixes = (
        "Không thể phân tích kỳ học",
        "Đã tồn tại file",
        "Không tìm thấy môn",
        "Không tìm thấy dữ liệu đề thi",
        "Tiêu đề không hợp lệ",
    )
    if isinstance(e, (ValueError, RuntimeError)) and any(err_str.startswith(prefix) for prefix in known_validation_prefixes):
        code = f"VAL-{uuid.uuid4().hex[:6].upper()}"
        return f"{err_str} (Mã lỗi: {code})", code, False

    # 4. Unexpected internal errors
    code = f"ERR-{uuid.uuid4().hex[:8].upper()}"
    return f"Có lỗi nội bộ khi soạn đề, mã lỗi {code}, xem log.", code, False


class JobOrchestrator:
    """
    Orchestrates exam compilation jobs and SSE progress broadcasting.
    """

    def __init__(self):
        self._listeners: Dict[str, List[asyncio.Queue]] = {}
        self._event_history: Dict[str, List[Dict[str, Any]]] = {}
        self._running_tasks: Dict[str, asyncio.Task] = {}
        self._cancel_events: Dict[str, threading.Event] = {}
        self.storage = LocalStorage()

    def _broadcast(self, job_id: str, event_data: Dict[str, Any]):
        """Append event to history and broadcast to active SSE listeners."""
        if job_id not in self._event_history:
            self._event_history[job_id] = []
        self._event_history[job_id].append(event_data)

        if job_id in self._listeners:
            for queue in self._listeners[job_id]:
                try:
                    queue.put_nowait(event_data)
                except Exception as e:
                    logger.debug(f"Error putting event to queue for job {job_id}: {e}")

    async def subscribe(self, job_id: str) -> AsyncGenerator[str, None]:
        """Subscribe to SSE events for a job."""
        queue: asyncio.Queue = asyncio.Queue()
        if job_id not in self._listeners:
            self._listeners[job_id] = []
        self._listeners[job_id].append(queue)

        try:
            # Yield historical events first
            if job_id in self._event_history:
                for event in self._event_history[job_id]:
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

            # Stream incoming events
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("type") in ("completed", "error"):
                    break
        finally:
            if job_id in self._listeners and queue in self._listeners[job_id]:
                self._listeners[job_id].remove(queue)

    async def start_job(
        self,
        subject_code: str,
        exam_type: ExamType = ExamType.FE,
        limit: int = 4,
        force_refresh: bool = False,
        exam_ids: Optional[List[int]] = None,
        platform: str = "fuoverflow",
        exam_titles: Optional[Dict[str, str]] = None,
    ) -> Job:
        """Create and launch a background exam compilation job."""
        job_uuid = str(uuid.uuid4())
        effective_count = len(exam_ids) if exam_ids else limit

        async with async_session_factory() as db:
            active_cfg = await get_active_settings(db, job_options={"crawl": {"default_count": effective_count}})
            job = Job(
                job_id=job_uuid,
                subject_code=subject_code.upper(),
                exam_type=exam_type,
                exam_count=effective_count,
                status=JobStatus.PENDING,
                current_step="init",
                progress_percentage=0.0,
                config_snapshot=active_cfg,
                details={
                    "subject_code": subject_code.upper(),
                    "exam_type": exam_type.value,
                    "limit": effective_count,
                    "force_refresh": force_refresh,
                    "exam_ids": exam_ids,
                    "platform": platform,
                    "exam_titles": exam_titles or {},
                },
            )
            db.add(job)
            await db.commit()
            await db.refresh(job)

        self._event_history[job_uuid] = []
        self._cancel_events[job_uuid] = threading.Event()
        task = asyncio.create_task(
            self._run_job_pipeline(job_uuid, subject_code.upper(), exam_type, effective_count, force_refresh, exam_ids=exam_ids, platform=platform)
        )
        self._running_tasks[job_uuid] = task
        return job

    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a running or pending job (including during backoff/circuit breaker)."""
        cancel_ev = self._cancel_events.get(job_id)
        if cancel_ev:
            cancel_ev.set()

        task = self._running_tasks.get(job_id)
        if task and not task.done():
            task.cancel()

        async with async_session_factory() as db:
            stmt = select(Job).where(Job.job_id == job_id)
            res = await db.execute(stmt)
            job = res.scalar_one_or_none()
            if job and job.status in (JobStatus.RUNNING, JobStatus.PENDING):
                job.status = JobStatus.FAILED
                job.error_message = "Đã huỷ bởi người dùng"
                await db.commit()
                self._broadcast(job_id, {"type": "error", "step": "cancelled", "message": "Tiến trình đã bị huỷ bởi người dùng."})
                return True
        return False

    async def resume_job(self, job_id: str) -> Optional[Job]:
        """Resume a stopped or failed job from its last completed state."""
        existing_cancel = self._cancel_events.get(job_id)
        if existing_cancel:
            existing_cancel.set()
        existing_task = self._running_tasks.get(job_id)
        if existing_task and not existing_task.done():
            existing_task.cancel()

        async with async_session_factory() as db:
            stmt = select(Job).where(Job.job_id == job_id)
            res = await db.execute(stmt)
            job = res.scalar_one_or_none()
            if not job:
                return None

            job.status = JobStatus.PENDING
            job.error_message = None
            job.current_step = "resuming"
            await db.commit()
            await db.refresh(job)

        self._broadcast(job_id, {
            "type": "log",
            "step": "resuming",
            "message": "Đang khôi phục và tiếp tục tiến trình từ điểm dừng...",
            "progress": job.progress_percentage or 10,
        })

        force_ref = bool(job.details.get("force_refresh", False)) if job.details else False
        saved_exam_ids = job.details.get("exam_ids") if job.details else None
        platform = job.details.get("platform", "fuoverflow") if job.details else "fuoverflow"
        self._cancel_events[job.job_id] = threading.Event()
        task = asyncio.create_task(
            self._run_job_pipeline(job.job_id, job.subject_code, job.exam_type, job.exam_count, force_ref, exam_ids=saved_exam_ids, platform=platform)
        )
        self._running_tasks[job.job_id] = task
        return job

    async def retry_failed_exams(self, job_id: str) -> Optional[Job]:
        """Retry only failed (or warning) exams from a previous job, reusing cache for successful parts."""
        existing_cancel = self._cancel_events.get(job_id)
        if existing_cancel:
            existing_cancel.set()
        existing_task = self._running_tasks.get(job_id)
        if existing_task and not existing_task.done():
            existing_task.cancel()

        async with async_session_factory() as db:
            stmt = select(Job).where(Job.job_id == job_id)
            res = await db.execute(stmt)
            job = res.scalar_one_or_none()
            if not job:
                return None

            details = dict(job.details or {})
            exam_results = list(details.get("exam_results") or [])
            failed_exams = list(details.get("failed_exams") or [])

            retry_ids: List[int] = []
            for item in failed_exams:
                tid = item.get("thread_id")
                if tid is not None and tid not in retry_ids:
                    retry_ids.append(int(tid))
            for item in exam_results:
                if item.get("status") in ("failed", "completed_with_warnings"):
                    tid = item.get("thread_id")
                    if tid is not None and tid not in retry_ids:
                        retry_ids.append(int(tid))

            if not retry_ids:
                return job

            # Giữ lại các file đã thành công hoàn toàn; các đề cần thử lại sẽ chạy với force_refresh=False để tận dụng cache
            details["retry_exam_ids"] = retry_ids
            details["failed_exams"] = [f for f in failed_exams if f.get("thread_id") not in retry_ids]
            job.details = details
            job.status = JobStatus.PENDING
            job.error_message = None
            job.current_step = "retrying_failed"
            await db.commit()
            await db.refresh(job)

        self._event_history[job.job_id] = []
        self._cancel_events[job.job_id] = threading.Event()
        self._broadcast(job.job_id, {
            "type": "log",
            "step": "retrying_failed",
            "message": f"Đang thử lại {len(retry_ids)} đề bị lỗi/cảnh báo (dùng lại cache phần đã xong)...",
            "progress": 5,
        })

        platform = (job.details or {}).get("platform", "fuexam")
        task = asyncio.create_task(
            self._run_job_pipeline(
                job.job_id,
                job.subject_code,
                job.exam_type,
                len(retry_ids),
                force_refresh=False,
                exam_ids=retry_ids,
                platform=platform,
            )
        )
        self._running_tasks[job.job_id] = task
        return job

    async def _run_job_pipeline(
        self,
        job_id: str,
        subject_code: str,
        exam_type: ExamType,
        limit: int,
        force_refresh: bool = False,
        exam_ids: Optional[List[int]] = None,
        platform: str = "fuoverflow",
    ):
        """Execute the compilation pipeline step-by-step."""
        if platform.lower() == "fuexam":
            return await self._run_fuexam_job_pipeline(
                job_id=job_id,
                subject_code=subject_code,
                exam_type=exam_type,
                limit=limit,
                force_refresh=force_refresh,
                exam_ids=exam_ids,
            )

        logger.info(f"Starting job pipeline {job_id} for {subject_code} ({exam_type.value}, limit={limit}, force_refresh={force_refresh})...")
        created_files: List[Dict[str, Any]] = []

        async with async_session_factory() as db:
            try:
                # 1. Update job to RUNNING
                stmt = select(Job).where(Job.job_id == job_id)
                res = await db.execute(stmt)
                job = res.scalar_one()
                job.status = JobStatus.RUNNING
                job.current_step = "auth_check"
                initial_details = dict(job.details or {})
                created_files = list(initial_details.get("files", []))
                job.details = {**initial_details, "started_at": datetime.utcnow().isoformat()}
                job_cfg = job.config_snapshot or (await get_active_settings(db))
                await db.commit()

                self._broadcast(job_id, {
                    "type": "log",
                    "step": "auth_check",
                    "message": "Kiểm tra phiên đăng nhập tài khoản FUOverflow...",
                    "progress": 5,
                })

                # 2. Check Authentication
                bm = get_browser_manager()
                try:
                    is_auth = await run_in_browser_thread(bm.ensure_logged_in, 30, True)
                    if not is_auth:
                        raise AuthenticationRequiredError("Phiên đăng nhập hết hạn hoặc chưa xác thực")
                except AuthenticationRequiredError as auth_err:
                    error_msg = f"Cần đăng nhập lại FUOverflow: {auth_err}"
                    logger.error(f"Job {job_id} failed: {error_msg}")
                    job.status = JobStatus.FAILED
                    job.error_message = error_msg
                    job.current_step = "auth_failed"
                    job.details = {**job.details, "completed_at": datetime.utcnow().isoformat()}
                    await db.commit()
                    self._broadcast(job_id, {
                        "type": "error",
                        "step": "auth_check",
                        "message": error_msg,
                    })
                    return
                except Exception as auth_err:
                    error_msg = f"Lỗi xác thực phiên đăng nhập: {auth_err}"
                    logger.error(f"Job {job_id} failed: {error_msg}")
                    job.status = JobStatus.FAILED
                    job.error_message = error_msg
                    job.current_step = "auth_failed"
                    job.details = {**job.details, "completed_at": datetime.utcnow().isoformat()}
                    await db.commit()
                    self._broadcast(job_id, {
                        "type": "error",
                        "step": "auth_check",
                        "message": error_msg,
                    })
                    return

                self._broadcast(job_id, {
                    "type": "log",
                    "step": "auth_check",
                    "message": "Phiên đăng nhập hợp lệ. Bắt đầu tìm kiếm đề thi...",
                    "progress": 15,
                })

                # 3. Find subject in DB
                s_stmt = select(Subject).where(Subject.code == subject_code)
                s_res = await db.execute(s_stmt)
                subject = s_res.scalar_one_or_none()

                if not subject:
                    # Try to populate subjects first
                    subjects = await get_or_fetch_subjects(db)
                    subject = next((s for s in subjects if s.code == subject_code), None)

                if not subject:
                    subject = Subject(
                        code=subject_code,
                        name=f"Môn học {subject_code}",
                        forum_url=f"https://fuoverflow.com/forums/{subject_code}/",
                    )
                    db.add(subject)
                    await db.flush()

                # 4. Crawl Exams
                job.current_step = "crawling_exams"
                await db.commit()

                self._broadcast(job_id, {
                    "type": "log",
                    "step": "crawling_exams",
                    "message": f"Đang quét danh sách đề thi {exam_type.value} cho môn {subject_code}...",
                    "progress": 25,
                })

                if exam_ids and len(exam_ids) > 0:
                    # Query specific exams requested by user
                    stmt = select(Exam).where(Exam.id.in_(exam_ids), Exam.subject_id == subject.id)
                    res = await db.execute(stmt)
                    exams_map = {e.id: e for e in res.scalars().all()}
                    exams = [exams_map[eid] for eid in exam_ids if eid in exams_map]
                    # If some exams are missing from DB, crawl subject to populate them
                    if len(exams) < len(exam_ids):
                        all_crawled = await crawl_subject_exams(
                            subject=subject,
                            exam_type=exam_type,
                            limit=max(limit, 20),
                            db=db,
                        )
                        crawled_map = {e.id: e for e in all_crawled}
                        exams = [exams_map.get(eid) or crawled_map.get(eid) for eid in exam_ids]
                        exams = [e for e in exams if e is not None]
                else:
                    exams = await crawl_subject_exams(
                        subject=subject,
                        exam_type=exam_type,
                        limit=limit,
                        db=db,
                    )

                if not exams:
                    warn_msg = f"Không tìm thấy đề thi {exam_type.value} nào cho môn {subject_code} trên diễn đàn."
                    logger.warning(warn_msg)
                    job.status = JobStatus.FAILED
                    job.current_step = "error"
                    job.error_message = warn_msg
                    job.details = {**job.details, "error": warn_msg, "failed_at": datetime.utcnow().isoformat()}
                    await db.commit()
                    self._broadcast(job_id, {
                        "type": "error",
                        "message": warn_msg,
                    })
                    return

                total_exams = len(exams)
                self._broadcast(job_id, {
                    "type": "log",
                    "step": "crawling_exams",
                    "message": f"Tìm thấy {total_exams} đề thi {exam_type.value}. Bắt đầu xử lý từng đề...",
                    "progress": 35,
                    "total_exams": total_exams,
                })

                # 5. Process Each Exam (Crawl questions -> Build .docx)
                total_all_questions = 0
                all_exam_question_pairs = []

                for exam_idx, exam in enumerate(exams, start=1):
                    exam_progress_base = 35 + int(((exam_idx - 1) / total_exams) * 55)

                    # Cache Check with Settings Hash & Comment Freshness
                    current_settings_hash = compute_doc_settings_hash(job_cfg)
                    cached_filename = format_exam_docx_filename(subject_code, exam, platform="fuoverflow")
                    cached_path = settings.STORAGE_DIR / "output" / "FUO" / subject_code / cached_filename
                    if not cached_path.exists():
                        legacy_path = settings.STORAGE_DIR / "output" / subject_code / cached_filename
                        if legacy_path.exists():
                            cached_path = legacy_path
                    meta_path = cached_path.with_name(cached_path.name + ".meta.json")

                    has_cached_doc = False
                    cached_time_str = "trước đó"

                    # Calculate latest comment time for questions in this exam
                    latest_comment_ts = 0.0
                    q_stmt = select(Question).where(Question.exam_id == exam.id).order_by(Question.index)
                    q_res = await db.execute(q_stmt)
                    existing_questions = list(q_res.scalars().all())

                    if existing_questions:
                        q_ids = [q.id for q in existing_questions]
                        c_res = await db.execute(
                            select(func.max(Comment.created_at)).where(Comment.question_id.in_(q_ids))
                        )
                        max_created = c_res.scalar()
                        if max_created:
                            latest_comment_ts = max_created.timestamp()

                    if not force_refresh and cached_path.exists() and cached_path.stat().st_size > 5000:
                        if meta_path.exists():
                            try:
                                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                                if meta.get("settings_hash") == current_settings_hash:
                                    meta_created_ts = meta.get("created_at_epoch", cached_path.stat().st_mtime)
                                    if meta_created_ts >= latest_comment_ts:
                                        has_cached_doc = True
                                        cached_time_str = meta.get("created_at_formatted") or datetime.fromtimestamp(cached_path.stat().st_mtime).strftime("%H:%M %d/%m/%Y")
                            except Exception as meta_err:
                                logger.warning(f"Could not read/parse metadata cache file {meta_path}: {meta_err}", exc_info=True)
                        elif len(existing_questions) >= max(exam.question_count or 10, 10) and all(q.local_image_path and Path(q.local_image_path).exists() for q in existing_questions):
                            has_cached_doc = True
                            cached_time_str = datetime.fromtimestamp(cached_path.stat().st_mtime).strftime("%H:%M %d/%m/%Y")

                    if has_cached_doc:
                        logger.info(f"[CACHE HIT] Reusing existing document for {exam.title}: {cached_path.name}")
                        self._broadcast(job_id, {
                            "type": "log",
                            "step": "cache_hit",
                            "message": f"Tạo từ bộ nhớ đệm lúc {cached_time_str} ({exam.title})",
                            "progress": min(exam_progress_base + int(50 / total_exams), 95),
                        })
                        rel_output = str(cached_path.resolve().relative_to(settings.BASE_DIR.resolve())).replace("\\", "/")
                        meta_cached = {}
                        if meta_path.exists():
                            try:
                                meta_cached = json.loads(meta_path.read_text(encoding="utf-8"))
                            except Exception:
                                pass

                        file_info = {
                            "filename": cached_path.name,
                            "path": rel_output,
                            "exam_title": exam.title,
                            "questions_count": len(existing_questions),
                            "size_bytes": cached_path.stat().st_size,
                            "cached": True,
                            "cached_at": cached_time_str,
                            "can_rebuild": True,
                            "platform": "fuoverflow",
                            "image_count": meta_cached.get("image_count", 0),
                            "comment_count": meta_cached.get("comment_count", len(existing_questions) - meta_cached.get("ai_count", 0)),
                            "source_breakdown": meta_cached.get("source_breakdown", {}),
                            "confident_count": meta_cached.get("confident_count", 0),
                            "weak_count": meta_cached.get("weak_count", 0),
                            "conflict_count": meta_cached.get("conflict_count", 0),
                            "ai_count": meta_cached.get("ai_count", 0),
                            "review_needed_questions": meta_cached.get("review_needed_questions", []),
                        }
                        if not any(f.get("filename") == cached_path.name for f in created_files):
                            created_files.append(file_info)

                        job.details = {
                            **job.details,
                            "files": list(created_files),
                            "completed_exams": exam_idx,
                            "total_exams": total_exams,
                        }
                        if not job.result_file_path:
                            job.result_file_path = rel_output
                        await db.commit()

                        self._broadcast(job_id, {
                            "type": "exam_completed",
                            "step": "cache_hit",
                            "message": f"Đã lấy từ bộ nhớ đệm lúc {cached_time_str}: {exam.title}",
                            "completed_file": file_info,
                            "files": list(created_files),
                        })
                        all_exam_question_pairs.append((exam, existing_questions))
                        continue

                    self._broadcast(job_id, {
                        "type": "log",
                        "step": "crawling_questions",
                        "message": f"[{exam_idx}/{total_exams}] Đang tải câu hỏi đề: {exam.title}...",
                        "progress": exam_progress_base,
                        "current_exam": exam_idx,
                        "total_exams": total_exams,
                    })

                    def on_q_progress(curr_q: int, tot_q: int, file_name: str):
                        step_prog = exam_progress_base + int((curr_q / max(tot_q, 1)) * (55 / total_exams))
                        self._broadcast(job_id, {
                            "type": "progress",
                            "step": "crawling_questions",
                            "message": f"Đã tải {file_name} ({curr_q}/{tot_q})",
                            "progress": min(step_prog, 92),
                            "current_question": curr_q,
                            "total_questions": tot_q,
                        })

                    questions = await crawl_exam_questions(
                        exam=exam,
                        subject_code=subject_code,
                        db=db,
                        storage=self.storage,
                        on_progress=on_q_progress,
                    )

                    total_all_questions += len(questions)

                    # Crawl comments for questions
                    self._broadcast(job_id, {
                        "type": "log",
                        "step": "crawling_comments",
                        "message": f"[{exam_idx}/{total_exams}] Đang thu thập bình luận cho đề: {exam.title}...",
                        "progress": exam_progress_base + int(30 / total_exams),
                        "current_exam": exam_idx,
                        "total_exams": total_exams,
                    })

                    def on_c_progress(curr_c: int, tot_c: int, msg: str):
                        step_prog = exam_progress_base + int(30 / total_exams) + int((curr_c / max(tot_c, 1)) * (20 / total_exams))
                        self._broadcast(job_id, {
                            "type": "progress",
                            "step": "crawling_comments",
                            "message": f"Thu thập bình luận: {msg}",
                            "progress": min(step_prog, 92),
                            "current_question": curr_c,
                            "total_questions": tot_c,
                        })

                    await crawl_exam_comments(
                        exam=exam,
                        subject_code=subject_code,
                        db=db,
                        storage=self.storage,
                        on_progress=on_c_progress,
                    )

                    # Crop questions by layout with self-adaptation across exam
                    cropped_dir = settings.STORAGE_DIR / "cropped" / subject_code / f"exam_{exam.id}"
                    crop_summary = crop_exam_images(
                        exam_id=exam.id,
                        exam_title=exam.title,
                        questions=questions,
                        cropped_dir=cropped_dir,
                    )
                    exam.crop_layout = crop_summary.dominant_layout
                    for q, res in zip(questions, crop_summary.results):
                        q.crop_layout = res.layout
                        q.crop_warnings = res.warnings
                        if res.output_path:
                            q.cropped_image_path = str(res.output_path)
                        if res.choice_hint_path:
                            q.choice_hint_path = str(res.choice_hint_path)
                        q.choice_hint_width_px = res.choice_hint_width_px
                    await db.commit()

                    self._broadcast(job_id, {
                        "type": "log",
                        "step": "cropping",
                        "message": f"Đã cắt ảnh đề '{exam.title}': kiểu {crop_summary.dominant_layout}, {crop_summary.clean_questions}/{crop_summary.total_questions} ảnh sạch"
                        + (f" (Cảnh báo: {crop_summary.flagged_questions} ảnh cần xem lại)" if crop_summary.flagged_questions else ""),
                        "progress": min(exam_progress_base + int(40 / total_exams), 95),
                    })

                    # Tally votes for each question
                    self._broadcast(job_id, {
                        "type": "log",
                        "step": "tallying_votes",
                        "message": f"[{exam_idx}/{total_exams}] Đang phân tích và bỏ phiếu đáp án theo số đông cho đề: {exam.title}...",
                        "progress": exam_progress_base + int(45 / total_exams),
                    })

                    ai_service = get_ai_check_service()
                    job_cfg = job.config_snapshot or (await get_active_settings(db))
                    ai_enabled = job_cfg.get("ai", {}).get("enabled", True)
                    ai_mode = job_cfg.get("ai", {}).get("mode", "only_uncertain")
                    ai_weight = float(job_cfg.get("voting", {}).get("ai_weight", 1.0))
                    max_opt_letter = job_cfg.get("voting", {}).get("max_option_letter", "H")

                    for q in questions:
                        await db.refresh(q, ["comments", "answer"])

                        # Preliminary community tally to determine if AI call is needed
                        prelim_res = tally_votes(
                            q.comments,
                            ai_weight=ai_weight,
                            max_option_letter=max_opt_letter,
                        )

                        need_ai = False
                        # Never call AI for questions with missing_options
                        has_missing_options = "missing_options" in (q.crop_warnings or [])
                        if ai_enabled and ai_service.is_available() and not has_missing_options:
                            if ai_mode == "all":
                                need_ai = True
                            elif ai_mode == "off":
                                need_ai = False
                            else:  # "only_uncertain" (default)
                                if prelim_res.status in (AnswerStatus.CONFLICT, AnswerStatus.WEAK, AnswerStatus.NO_DATA) or prelim_res.confidence < 0.80:
                                    need_ai = True

                        ai_votes = []
                        ai_options = {}
                        img_path = getattr(q, "cropped_image_path", None) or getattr(q, "local_image_path", None)
                        if need_ai and img_path and ai_service.is_available():
                            local_img = Path(img_path) if Path(img_path).is_absolute() else settings.BASE_DIR / img_path
                            if local_img.exists():
                                analyses = ai_service.analyze_question_ensemble(local_img, job_id=job_id)
                                for a in analyses:
                                    ai_votes.append({
                                        "provider": a.provider or "ai",
                                        "answers": a.answers,
                                        "confidence": a.confidence,
                                    })
                                    if a.options:
                                        ai_options.update(a.options)

                        # Final tally with AI contributions if called
                        voting_res = tally_votes(
                            q.comments,
                            ai_votes=ai_votes if ai_votes else None,
                            ai_weight=ai_weight,
                            max_option_letter=max_opt_letter,
                        )

                        breakdown = dict(voting_res.vote_breakdown)
                        if need_ai and not ai_votes and not ai_service.is_available():
                            breakdown["ai_pending"] = True
                        if ai_options:
                            breakdown["_options"] = ai_options
                        if ai_votes:
                            breakdown["_ai_votes"] = ai_votes

                        if not q.answer:
                            ans = Answer(
                                question_id=q.id,
                                answer_set=voting_res.answer_set,
                                status=voting_res.status,
                                confidence=voting_res.confidence,
                                valid_comments_count=voting_res.voters_count,
                                vote_breakdown=breakdown,
                            )
                            db.add(ans)
                            q.answer = ans
                        else:
                            q.answer.answer_set = voting_res.answer_set
                            q.answer.status = voting_res.status
                            q.answer.confidence = voting_res.confidence
                            q.answer.valid_comments_count = voting_res.voters_count
                            q.answer.vote_breakdown = breakdown
                    await db.commit()

                    all_exam_question_pairs.append((exam, questions))
                    ans_fmt = job_cfg.get("export", {}).get("answer_format", "letter_keyword")

                    # Build .docx for this exam
                    self._broadcast(job_id, {
                        "type": "log",
                        "step": "building_docx",
                        "message": f"Đang xuất file .docx cho đề: {exam.title} ({len(questions)} câu)...",
                        "progress": min(exam_progress_base + int(50 / total_exams), 95),
                    })

                    q_ids = [q.id for q in questions]
                    ans_res = await db.execute(select(Answer).where(Answer.question_id.in_(q_ids)))
                    answers_map = {a.question_id: a for a in ans_res.scalars().all()}

                    fuo_out_dir = settings.STORAGE_DIR / "output" / "FUO" / subject_code
                    fuo_out_dir.mkdir(parents=True, exist_ok=True)

                    docx_path = build_exam_docx(
                        subject_code=subject_code,
                        exam=exam,
                        questions=questions,
                        output_dir=fuo_out_dir,
                        platform="fuoverflow",
                        answer_format=ans_fmt,
                        multi_choice_format=job_cfg.get("export", {}).get("multi_choice_format", "comma"),
                        highlight_check_needed=job_cfg.get("export", {}).get("highlight_low_confidence", True),
                        add_divider=job_cfg.get("export", {}).get("show_separator_line", True),
                        add_question_number=job_cfg.get("export", {}).get("show_question_number", True),
                        unsupported_layout_warning=crop_summary.fallback_to_raw,
                        use_raw_fallback=crop_summary.fallback_to_raw,
                        answers_map=answers_map,
                    )

                    # Save sidecar metadata for cache invalidation & review stats
                    meta_path = docx_path.with_name(docx_path.name + ".meta.json")
                    existing_meta = {}
                    if meta_path.exists():
                        try:
                            existing_meta = json.loads(meta_path.read_text(encoding="utf-8"))
                        except Exception:
                            pass

                    now_dt = datetime.now()
                    meta_data = {
                        **existing_meta,
                        "settings_hash": current_settings_hash,
                        "created_at": now_dt.isoformat(),
                        "created_at_epoch": now_dt.timestamp(),
                        "created_at_formatted": now_dt.strftime("%H:%M %d/%m/%Y"),
                        "latest_comment_timestamp": latest_comment_ts,
                        "questions_count": len(questions),
                        "exam_title": exam.title,
                        "platform": "fuoverflow",
                    }
                    meta_path.write_text(json.dumps(meta_data, ensure_ascii=False, indent=2), encoding="utf-8")

                    rel_output = str(docx_path.resolve().relative_to(settings.BASE_DIR.resolve())).replace("\\", "/")
                    file_info = {
                        "filename": docx_path.name,
                        "path": rel_output,
                        "exam_title": exam.title,
                        "questions_count": len(questions),
                        "size_bytes": docx_path.stat().st_size if docx_path.exists() else 0,
                        "cached": False,
                        "cached_at": now_dt.strftime("%H:%M %d/%m/%Y"),
                        "can_rebuild": True,
                        "platform": "fuoverflow",
                        "image_count": meta_data.get("image_count", 0),
                        "comment_count": meta_data.get("comment_count", len(questions) - meta_data.get("ai_count", 0)),
                        "source_breakdown": meta_data.get("source_breakdown", {}),
                        "confident_count": meta_data.get("confident_count", 0),
                        "weak_count": meta_data.get("weak_count", 0),
                        "conflict_count": meta_data.get("conflict_count", 0),
                        "ai_count": meta_data.get("ai_count", 0),
                        "review_needed_questions": meta_data.get("review_needed_questions", []),
                    }
                    if not any(f.get("filename") == docx_path.name for f in created_files):
                        created_files.append(file_info)

                    # Persist completed files immediately to DB
                    job.details = {
                        **job.details,
                        "files": list(created_files),
                        "completed_exams": exam_idx,
                        "total_exams": total_exams,
                    }
                    if not job.result_file_path:
                        job.result_file_path = rel_output
                    await db.commit()

                    self._broadcast(job_id, {
                        "type": "exam_completed",
                        "step": "building_docx",
                        "message": f"Đã hoàn tất biên soạn đề {exam_idx}/{total_exams}: {exam.title}",
                        "completed_file": file_info,
                        "files": list(created_files),
                        "current_exam": exam_idx,
                        "total_exams": total_exams,
                        "progress": min(exam_progress_base + int(50 / total_exams), 95),
                    })

                # Optional: Build merged .docx if merge=True and multiple exams were compiled
                should_merge = bool(job_cfg.get("export", {}).get("merge", False))
                if should_merge and len(all_exam_question_pairs) > 1:
                    self._broadcast(job_id, {
                        "type": "log",
                        "step": "building_merged_docx",
                        "message": f"Đang gộp {len(all_exam_question_pairs)} đề vào một file Word chung...",
                        "progress": 96,
                    })
                    all_q_ids = [q.id for _, q_list in all_exam_question_pairs for q in q_list]
                    all_ans_res = await db.execute(select(Answer).where(Answer.question_id.in_(all_q_ids)))
                    all_ans_map = {a.question_id: a for a in all_ans_res.scalars().all()}

                    merged_docx_path = build_merged_docx(
                        subject_code=subject_code,
                        exams_data=all_exam_question_pairs,
                        answer_format=ans_fmt,
                        multi_choice_format=job_cfg.get("export", {}).get("multi_choice_format", "comma"),
                        highlight_check_needed=job_cfg.get("export", {}).get("highlight_low_confidence", True),
                        add_divider=job_cfg.get("export", {}).get("show_separator_line", True),
                        add_question_number=job_cfg.get("export", {}).get("show_question_number", True),
                        answers_map=all_ans_map,
                    )
                    rel_merged = str(merged_docx_path.resolve().relative_to(settings.BASE_DIR.resolve())).replace("\\", "/")
                    created_files.append({
                        "filename": merged_docx_path.name,
                        "path": rel_merged,
                        "exam_title": f"{subject_code.upper()} - Toàn bộ {len(all_exam_question_pairs)} đề (Gộp)",
                        "questions_count": total_all_questions,
                        "size_bytes": merged_docx_path.stat().st_size if merged_docx_path.exists() else 0,
                    })

                # 6. Complete Job
                job.status = JobStatus.COMPLETED
                job.current_step = "completed"
                job.progress_percentage = 100.0
                if created_files:
                    job.result_file_path = created_files[0]["path"]
                job.details = {
                    **job.details,
                    "completed_at": datetime.utcnow().isoformat(),
                    "files": created_files,
                    "total_exams": total_exams,
                    "total_questions": total_all_questions,
                }
                await db.commit()

                self._broadcast(job_id, {
                    "type": "completed",
                    "step": "completed",
                    "message": f"Hoàn tất biên soạn {total_exams} đề ({total_all_questions} câu hỏi)!",
                    "progress": 100,
                    "files": created_files,
                    "total_exams": total_exams,
                    "total_questions": total_all_questions,
                })
                logger.info(f"Job {job_id} completed successfully.")

            except AuthenticationRequiredError as auth_err:
                logger.error(f"Job {job_id} requires login: {auth_err}")
                job.status = JobStatus.FAILED
                job.error_message = str(auth_err)
                job.current_step = "auth_required"
                job.completed_at = datetime.utcnow()
                job.details = {
                    **job.details,
                    "files": list(created_files),
                    "failed_at": datetime.utcnow().isoformat(),
                }
                await db.commit()
                self._broadcast(job_id, {
                    "type": "error",
                    "step": "auth_required",
                    "message": str(auth_err),
                    "files": list(created_files),
                })

            except Exception as e:
                user_msg, err_code, is_retryable = classify_job_error(e)
                logger.exception(f"Unexpected error [{err_code}] executing job {job_id}: {e}")
                job.status = JobStatus.FAILED
                job.error_message = user_msg
                job.current_step = "failed"
                job.completed_at = datetime.utcnow()
                job.details = {
                    **job.details,
                    "error_code": err_code,
                    "is_retryable": is_retryable,
                    "files": list(created_files),
                    "failed_at": datetime.utcnow().isoformat(),
                }
                await db.commit()
                self._broadcast(job_id, {
                    "type": "error",
                    "step": "failed",
                    "message": user_msg,
                    "error_code": err_code,
                    "is_retryable": is_retryable,
                    "files": list(created_files),
                })
            finally:
                if job_id in self._running_tasks:
                    del self._running_tasks[job_id]
                self._cancel_events.pop(job_id, None)

    async def _run_fuexam_job_pipeline(
        self,
        job_id: str,
        subject_code: str,
        exam_type: ExamType,
        limit: int,
        force_refresh: bool = False,
        exam_ids: Optional[List[int]] = None,
    ):
        """Execute real compilation pipeline for fuexam.me with retry, circuit breaker, and per-question/per-exam isolation."""
        logger.info(f"Starting fuexam job pipeline {job_id} for {subject_code} ({exam_type.value}, limit={limit})...")
        created_files: List[Dict[str, Any]] = []
        exam_results: List[Dict[str, Any]] = []
        failed_exams: List[Dict[str, Any]] = []

        from backend.app.modules.crawler.fuexam_crawler import (
            get_authenticated_session,
            check_session_validity,
            extract_thread_questions,
            fetch_and_cache_media_image,
            fetch_and_cache_media_comments,
            FuexamHttpClient,
            CommentFetchError,
            JobCancelledError,
            set_active_fuexam_client,
            AuthenticationRequiredError as FuexamAuthError,
        )
        from backend.app.modules.crawler.fuexam_subjects import load_subject_map
        from backend.app.modules.export.image_cropper import crop_question_single
        from backend.app.modules.analysis.image_answer_reader import read_answer_from_image, read_choice_hint_n
        from backend.app.modules.analysis.voting import tally_votes
        from backend.app.modules.export.docx_builder import build_exam_docx

        cancel_ev = self._cancel_events.get(job_id) or threading.Event()
        self._cancel_events[job_id] = cancel_ev
        loop = asyncio.get_running_loop()

        def _thread_event_cb(ev: Dict[str, Any]) -> None:
            try:
                loop.call_soon_threadsafe(self._broadcast, job_id, ev)
            except RuntimeError:
                pass

        def _call_with_client(client: FuexamHttpClient, fn: Any, *args: Any, **kwargs: Any) -> Any:
            set_active_fuexam_client(client)
            try:
                return fn(*args, **kwargs)
            finally:
                set_active_fuexam_client(None)

        http_client: Optional[FuexamHttpClient] = None

        async with async_session_factory() as db:
            try:
                # 1. Update status to RUNNING
                stmt = select(Job).where(Job.job_id == job_id)
                res = await db.execute(stmt)
                job = res.scalar_one()
                job.status = JobStatus.RUNNING
                job.current_step = "auth_check"
                initial_details = dict(job.details or {})
                created_files = list(initial_details.get("files", []))
                exam_results = list(initial_details.get("exam_results", []))
                failed_exams = list(initial_details.get("failed_exams", []))
                job_cfg = job.config_snapshot or (await get_active_settings(db))
                crawl_cfg = job_cfg.get("crawl", {})
                min_delay = float(crawl_cfg.get("fuexam_min_delay_seconds", 0.4))

                http_client = FuexamHttpClient(
                    connect_timeout=crawl_cfg.get("fuexam_connect_timeout"),
                    read_timeout=crawl_cfg.get("fuexam_read_timeout"),
                    max_attempts=crawl_cfg.get("fuexam_max_retries"),
                    max_concurrency=crawl_cfg.get("fuexam_max_concurrency"),
                    min_delay_seconds=min_delay,
                    circuit_breaker_threshold=crawl_cfg.get("fuexam_circuit_breaker_threshold"),
                    circuit_breaker_pause_seconds=crawl_cfg.get("fuexam_circuit_breaker_pause_seconds"),
                    cancel_event=cancel_ev,
                    event_callback=_thread_event_cb,
                )

                job.details = {**initial_details, "started_at": datetime.utcnow().isoformat(), "platform": "fuexam"}
                await db.commit()

                self._broadcast(job_id, {
                    "type": "log",
                    "step": "auth_check",
                    "message": "Kiểm tra phiên đăng nhập tài khoản fuexam.me...",
                    "progress": 5,
                })

                # 2. Check Auth
                try:
                    session = get_authenticated_session()
                    is_valid = await asyncio.to_thread(_call_with_client, http_client, check_session_validity, session)
                    if not is_valid:
                        raise FuexamAuthError("Phiên đăng nhập fuexam.me đã hết hạn hoặc chưa đăng nhập.")
                except (JobCancelledError, asyncio.CancelledError):
                    raise
                except Exception as auth_err:
                    error_msg = f"Cần đăng nhập fuexam.me: {auth_err}"
                    logger.error(f"Fuexam job {job_id} failed auth: {error_msg}")
                    job.status = JobStatus.FAILED
                    job.error_message = error_msg
                    job.current_step = "auth_required"
                    job.details = {**job.details, "completed_at": datetime.utcnow().isoformat()}
                    await db.commit()
                    self._broadcast(job_id, {
                        "type": "error",
                        "step": "auth_required",
                        "message": error_msg,
                    })
                    return

                self._broadcast(job_id, {
                    "type": "log",
                    "step": "auth_check",
                    "message": "Phiên đăng nhập fuexam.me hợp lệ. Bắt đầu tìm kiếm đề thi...",
                    "progress": 15,
                })

                # 3. Subject in DB
                s_stmt = select(Subject).where(Subject.code == subject_code)
                s_res = await db.execute(s_stmt)
                subject = s_res.scalar_one_or_none()
                if not subject:
                    sub_map = load_subject_map()
                    subj_meta = sub_map.get(subject_code, {})
                    subject = Subject(
                        code=subject_code,
                        name=subj_meta.get("name", f"Môn {subject_code}"),
                        forum_url=subj_meta.get("forum_url", f"https://fuexam.me/forums/{subject_code.lower()}/"),
                        platform="fuexam",
                    )
                    db.add(subject)
                    await db.flush()

                # 4. Exams to compile
                job.current_step = "crawling_exams"
                await db.commit()

                exams_to_process = []
                seen_job_filenames: Dict[str, int] = {}
                passed_exam_titles = (job.details.get("exam_titles") if job.details else None) or {}
                if exam_ids and len(exam_ids) > 0:
                    for tid in exam_ids:
                        ex_stmt = select(Exam).where((Exam.id == tid) | (Exam.url.like(f"%/{tid}/%")))
                        ex_res = await db.execute(ex_stmt)
                        ex_obj = ex_res.scalar_one_or_none()
                        candidate_title = passed_exam_titles.get(str(tid)) or passed_exam_titles.get(tid)
                        if not ex_obj:
                            default_title = candidate_title or f"{subject_code} - {exam_type.value} (Thread {tid})"
                            if tid == 1174:
                                default_title = candidate_title or "PRM393 - SU26 - B5 - FE"
                            elif tid == 941:
                                default_title = candidate_title or "PRM393 - SU26 - FE - RE"
                            elif tid == 1587:
                                default_title = candidate_title or "MAE101 - FA26 - FE"
                            init_term = normalize_term(default_title)
                            ex_obj = Exam(
                                id=tid,
                                subject_id=subject.id,
                                title=default_title,
                                url=f"https://fuexam.me/threads/{tid}/",
                                exam_type=exam_type,
                                term=init_term,
                                platform="fuexam",
                                crop_layout="fuexam_2026",
                            )
                            db.add(ex_obj)
                            await db.flush()
                        else:
                            if candidate_title and ("Thread" in ex_obj.title or not ex_obj.term):
                                ex_obj.title = candidate_title
                                ex_term = normalize_term(candidate_title)
                                if ex_term:
                                    ex_obj.term = ex_term
                                await db.flush()
                        exams_to_process.append(ex_obj)
                else:
                    ex_stmt = select(Exam).where((Exam.id == 1174) | (Exam.url.like("%/1174/%")))
                    ex_res = await db.execute(ex_stmt)
                    ex_obj = ex_res.scalar_one_or_none()
                    candidate_title = passed_exam_titles.get("1174") or passed_exam_titles.get(1174)
                    if not ex_obj:
                        ex_obj = Exam(
                            id=1174,
                            subject_id=subject.id,
                            title=candidate_title or "PRM393 - SU26 - B5 - FE",
                            url="https://fuexam.me/threads/1174/",
                            exam_type=ExamType.FE,
                            term="SU26",
                            platform="fuexam",
                            crop_layout="fuexam_2026",
                        )
                        db.add(ex_obj)
                        await db.flush()
                    exams_to_process.append(ex_obj)

                exam_specs = [{"id": ex.id, "title": ex.title, "url": ex.url} for ex in exams_to_process]
                await db.commit()

                total_exams = len(exam_specs)
                total_all_questions = 0
                all_sources_count = {"image": 0, "comments": 0, "ai": 0, "total": 0}

                def _upsert_exam_result(entry: Dict[str, Any]) -> None:
                    tid = entry.get("thread_id")
                    idx = next((i for i, x in enumerate(exam_results) if x.get("thread_id") == tid), None)
                    if idx is not None:
                        exam_results[idx] = entry
                    else:
                        exam_results.append(entry)

                # 5. Process each exam with per-exam error isolation
                for exam_idx, ex_spec in enumerate(exam_specs, start=1):
                    if cancel_ev.is_set():
                        raise JobCancelledError("Tiến trình đã bị huỷ bởi người dùng.")

                    exam_id_val = ex_spec["id"]
                    exam_title_val = ex_spec["title"]
                    exam_url_val = ex_spec["url"]
                    exam = (await db.execute(select(Exam).where(Exam.id == exam_id_val))).scalar_one()
                    exam_progress_base = int(((exam_idx - 1) / total_exams) * 90)

                    self._broadcast(job_id, {
                        "type": "log",
                        "step": "crawling_questions",
                        "message": f"[{exam_idx}/{total_exams}] Đang quét các câu hỏi từ fuexam: {exam.title}...",
                        "progress": max(10, exam_progress_base),
                        "current_exam": exam_idx,
                        "total_exams": total_exams,
                    })

                    try:
                        raw_title, questions_meta = await asyncio.to_thread(
                            _call_with_client,
                            http_client,
                            extract_thread_questions,
                            exam.url,
                            session,
                        )
                        if not questions_meta:
                            raise RuntimeError(f"Không tìm thấy câu hỏi nào trong thread {exam.url}")

                        # Cập nhật danh tính đề từ TIÊU ĐỀ THREAD (không dùng fallback tạm)
                        clean_raw_title = re.sub(r"^\s*Đề\s*Thi\s*(?:FE|PE)?\s*[-–—:]\s*", "", raw_title, flags=re.IGNORECASE).strip()
                        clean_raw_title = re.sub(r"\(?\bThread\s*\d+\b\)?", "", clean_raw_title, flags=re.IGNORECASE).strip()
                        clean_raw_title = re.sub(r"\s*\|\s*FuExam.*$", "", clean_raw_title, flags=re.IGNORECASE).strip()
                        if clean_raw_title and not clean_raw_title.startswith("Đề Thi fuexam"):
                            exam.title = clean_raw_title

                        # Không bao giờ đoán bừa kỳ học ("SP26", "FA26"): Phải phân tích được từ tiêu đề
                        parsed_term = normalize_term(exam.title) or normalize_term(raw_title) or normalize_term(exam.term)
                        if not parsed_term:
                            err_msg = (
                                f"Không thể phân tích kỳ học (term) từ tiêu đề đề thi: '{exam.title}' (Thread {exam.id}). "
                                "Dừng biên soạn để tránh đặt tên đoán mặc định. Vui lòng bổ sung kỳ học vào tiêu đề thread (ví dụ: FA26, SU26, SP26)."
                            )
                            logger.error(err_msg)
                            raise RuntimeError(err_msg)
                        exam.term = parsed_term
                        await db.flush()

                        tot_q = len(questions_meta)
                        exam.question_count = tot_q
                        total_all_questions += tot_q

                        cropped_dir = settings.BASE_DIR / "data" / "cropped" / "fuexam" / subject_code / f"exam_{exam.id}"
                        cropped_dir.mkdir(parents=True, exist_ok=True)

                        question_objs: List[Question] = []
                        answers_map: Dict[int, Answer] = {}
                        exam_sources = {"image": 0, "comments": 0, "ai": 0, "no_data": 0}
                        fetch_failed_questions: List[int] = []
                        fetch_failed_details: List[Dict[str, Any]] = []

                        # Cấu hình AI cho fuexam (Requirement 6)
                        ai_service = get_ai_check_service()
                        ai_cfg = job_cfg.get("ai", {})
                        ai_enabled = ai_cfg.get("enabled", True)
                        ai_mode = ai_cfg.get("mode", "only_uncertain")
                        ai_weight = float(job_cfg.get("voting", {}).get("ai_weight", 1.0))
                        max_opt_letter = job_cfg.get("voting", {}).get("max_option_letter", "H")
                        warned_no_ai_key = False
                        ai_skipped_reason = None

                        for q_idx, q_item in enumerate(questions_meta, start=1):
                            if cancel_ev.is_set():
                                raise JobCancelledError("Tiến trình đã bị huỷ bởi người dùng.")

                            m_id = q_item["media_id"]
                            slug = q_item["slug"]
                            att_url = q_item["attachment_url"]

                            computed_prog = min(95, max(10, int((((exam_idx - 1) * tot_q + q_idx) / (total_exams * tot_q)) * 100)))

                            self._broadcast(job_id, {
                                "type": "progress",
                                "step": "crawling_questions",
                                "message": f"Đang tải câu {q_idx}/{tot_q}: {slug}",
                                "current_question": q_idx,
                                "total_questions": tot_q,
                                "current_exam": exam_idx,
                                "total_exams": total_exams,
                                "retry_attempt": 0,
                                "progress": computed_prog,
                            })

                            # Ghi sự kiện từng chặng (mỗi 5 câu)
                            if q_idx == 1 or q_idx % 5 == 0 or q_idx == tot_q:
                                self._broadcast(job_id, {
                                    "type": "log",
                                    "step": "crawling_questions",
                                    "message": f"[{exam_idx}/{total_exams}] Đang xử lý câu {q_idx}/{tot_q} cho đề: {exam.title}",
                                    "progress": computed_prog,
                                })

                            # Download image (isolated per question for invalid_image so remaining questions still export)
                            img_path: Optional[Path] = None
                            img_cached = False
                            source_image_invalid = False
                            try:
                                img_path, img_cached = await asyncio.to_thread(
                                    _call_with_client,
                                    http_client,
                                    fetch_and_cache_media_image,
                                    media_id=m_id,
                                    attachment_url=att_url,
                                    slug=slug,
                                    session=session,
                                    force_refresh=force_refresh,
                                    delay_seconds=min_delay,
                                )
                            except FuexamRequestError as img_req_err:
                                if img_req_err.error_type == "invalid_image":
                                    source_image_invalid = True
                                    logger.warning(
                                        f"Exam {exam.id} Q{q_idx} (media {m_id}): source image invalid; "
                                        f"isolating question and continuing."
                                    )
                                else:
                                    raise

                            # Download comments (isolated per question: never crashes exam on CommentFetchError)
                            comment_fetch_failed = False
                            comment_fetch_err_code: Optional[str] = None
                            try:
                                parsed_comms, comm_cached = await asyncio.to_thread(
                                    _call_with_client,
                                    http_client,
                                    fetch_and_cache_media_comments,
                                    media_id=m_id,
                                    slug=slug,
                                    session=session,
                                    force_refresh=force_refresh,
                                    delay_seconds=min_delay,
                                )
                            except CommentFetchError as cfe:
                                parsed_comms = []
                                comm_cached = False
                                comment_fetch_failed = True
                                comment_fetch_err_code = cfe.error_code
                                fetch_failed_questions.append(q_idx)
                                fetch_failed_details.append({
                                    "question": q_idx,
                                    "media_id": m_id,
                                    "error_type": cfe.error_type,
                                    "error_code": cfe.error_code,
                                    "message": str(cfe),
                                })
                                self._broadcast(job_id, {
                                    "type": "log",
                                    "step": "crawling_questions",
                                    "message": f"[{exam_idx}/{total_exams}] Câu {q_idx}/{tot_q}: Tải bình luận thất bại ({cfe.error_code}), cô lập câu lỗi và tiếp tục.",
                                    "progress": computed_prog,
                                })

                            # DB Question object
                            q_db_stmt = select(Question).where(Question.exam_id == exam.id, Question.index == q_idx)
                            q_db_res = await db.execute(q_db_stmt)
                            q_obj = q_db_res.scalar_one_or_none()
                            if not q_obj:
                                q_obj = Question(
                                    exam_id=exam.id,
                                    index=q_idx,
                                    file_name=img_path.name if img_path else f"{slug}.webp",
                                    media_id=str(m_id),
                                    local_image_path=str(img_path.resolve()) if img_path else None,
                                )
                                db.add(q_obj)
                                await db.flush()
                            else:
                                q_obj.file_name = img_path.name if img_path else f"{slug}.webp"
                                q_obj.media_id = str(m_id)
                                q_obj.local_image_path = str(img_path.resolve()) if img_path else None

                            # Crop image (isolated per-question if invalid)
                            if source_image_invalid or img_path is None:
                                q_obj.cropped_image_path = None
                                q_obj.crop_layout = "source_image_invalid"
                                q_obj.crop_warnings = ["source_image_invalid"]
                            else:
                                try:
                                    cropped_out = cropped_dir / f"q{q_idx:03d}.png"
                                    crop_res = crop_question_single(img_path, output_path=cropped_out)
                                    q_obj.cropped_image_path = str(cropped_out.resolve())
                                    q_obj.crop_layout = crop_res.layout
                                    q_obj.crop_warnings = crop_res.warnings
                                except Exception as crop_err:
                                    logger.warning(f"Exam {exam.id} Q{q_idx} crop failed ({crop_err}); marking source_image_invalid.")
                                    source_image_invalid = True
                                    q_obj.local_image_path = None
                                    q_obj.cropped_image_path = None
                                    q_obj.crop_layout = "source_image_invalid"
                                    q_obj.crop_warnings = ["source_image_invalid"]

                            # Determine answer:
                            # 1. Thử đọc dải đáp án xanh từ ảnh (CONFIDENT >= 0.80) -> Không bao giờ gọi AI
                            img_ans_res = read_answer_from_image(img_path) if (img_path and not source_image_invalid) else None
                            if img_ans_res and img_ans_res.letter and img_ans_res.confidence >= 0.80:
                                ans_set = img_ans_res.letters or [img_ans_res.letter]
                                ans_status = AnswerStatus.CONFIDENT
                                ans_conf = img_ans_res.confidence
                                vb = {"_source": "image", "_method": img_ans_res.method}
                                exam_sources["image"] += 1
                            else:
                                # 2. Tổng hợp bình luận cộng đồng
                                q_comments: List[Comment] = []
                                for i_c, c_raw in enumerate(parsed_comms, 1):
                                    q_comments.append(Comment(
                                        question_id=q_obj.id,
                                        comment_id=str(c_raw.get("comment_id", i_c)),
                                        author_hash=c_raw.get("author_hash", f"user_{i_c}"),
                                        raw_text=c_raw.get("raw_text", ""),
                                        upvotes=0,
                                    ))
                                prelim_res = tally_votes(q_comments, ai_weight=ai_weight, max_option_letter=max_opt_letter) if q_comments else None

                                # Nếu bình luận đã đạt CONFIDENT (>= 0.80) -> Không gọi AI
                                if prelim_res and prelim_res.status == AnswerStatus.CONFIDENT and prelim_res.confidence >= 0.80:
                                    ans_set = prelim_res.answer_set
                                    ans_status = AnswerStatus.CONFIDENT
                                    ans_conf = prelim_res.confidence
                                    vb = {"_source": "comments", **(prelim_res.vote_breakdown or {})}
                                    exam_sources["comments"] += 1
                                else:
                                    # Câu rơi vào WEAK, CONFLICT, hoặc NO_DATA -> Đủ điều kiện gọi AI
                                    has_missing_options = "missing_options" in (q_obj.crop_warnings or [])
                                    need_ai = ai_enabled and not has_missing_options and ai_mode != "off"
                                    ai_votes = []
                                    ai_options = {}

                                    if need_ai:
                                        if not ai_service.is_available():
                                            if not warned_no_ai_key:
                                                warned_no_ai_key = True
                                                ai_skipped_reason = "Chưa cấu hình API key hoặc hết hạn mức"
                                                self._broadcast(job_id, {
                                                    "type": "log",
                                                    "step": "crawling_questions",
                                                    "message": "AI được bật nhưng chưa cấu hình khóa API (hoặc hết hạn mức). Bỏ qua bước gọi AI.",
                                                })
                                        else:
                                            target_img = cropped_out if (cropped_out and cropped_out.exists()) else img_path
                                            if target_img:
                                                analyses = ai_service.analyze_question_ensemble(target_img, job_id=job_id)
                                            for a in analyses:
                                                ai_votes.append({
                                                    "provider": a.provider or "ai",
                                                    "answers": a.answers,
                                                    "confidence": a.confidence,
                                                })
                                                if a.options:
                                                    ai_options.update(a.options)

                                    # Bỏ phiếu kết hợp bình luận và AI (AI chỉ là 1 phiếu)
                                    if q_comments or ai_votes:
                                        final_res = tally_votes(
                                            q_comments,
                                            ai_votes=ai_votes if ai_votes else None,
                                            ai_weight=ai_weight,
                                            max_option_letter=max_opt_letter,
                                        )
                                        ans_set = final_res.answer_set
                                        ans_status = final_res.status
                                        ans_conf = final_res.confidence
                                        vb = dict(final_res.vote_breakdown or {})
                                        if ai_votes:
                                            vb["_ai_votes"] = ai_votes
                                            if not q_comments:
                                                vb["_source"] = "ai"
                                                exam_sources["ai"] += 1
                                            else:
                                                vb["_source"] = "comments"
                                                exam_sources["comments"] += 1
                                        else:
                                            vb["_source"] = "comments"
                                            exam_sources["comments"] += 1
                                    else:
                                        ans_set = ["?"]
                                        ans_status = AnswerStatus.NO_DATA
                                        ans_conf = 0.0
                                        vb = {"_source": "no_data"}
                                        exam_sources["no_data"] += 1

                                # Rule 2: Kiểm tra số chữ cái đáp án so với N từ dòng '(Choose N answers)'
                                expected_n = read_choice_hint_n(img_path, ai_service=ai_service) if (img_path and not source_image_invalid) else None
                                valid_answer_letters = [a for a in ans_set if a != "?"]
                                if expected_n is not None and expected_n > 0 and valid_answer_letters:
                                    if len(valid_answer_letters) != expected_n:
                                        logger.warning(
                                            f"Exam {exam.id} Question {q_idx}: Answer count mismatch. "
                                            f"Expected {expected_n} answers but got {valid_answer_letters}. "
                                            f"Flagging as '?' and moving to review_needed."
                                        )
                                        ans_set = ["?"]
                                        ans_status = AnswerStatus.CONFLICT
                                        ans_conf = 0.0
                                        vb["_mismatch_expected_n"] = expected_n
                                        vb["_original_answers"] = valid_answer_letters

                            if comment_fetch_failed:
                                vb["_comment_fetch_failed"] = True
                                if comment_fetch_err_code:
                                    vb["_comment_fetch_error"] = comment_fetch_err_code

                            # Save or update Answer in DB
                            ans_db_stmt = select(Answer).where(Answer.question_id == q_obj.id)
                            ans_db_res = await db.execute(ans_db_stmt)
                            ans_obj = ans_db_res.scalar_one_or_none()
                            if not ans_obj:
                                ans_obj = Answer(
                                    question_id=q_obj.id,
                                    answer_set=ans_set,
                                    status=ans_status,
                                    confidence=ans_conf,
                                    vote_breakdown=vb,
                                )
                                db.add(ans_obj)
                                await db.flush()
                            else:
                                ans_obj.answer_set = ans_set
                                ans_obj.status = ans_status
                                ans_obj.confidence = ans_conf
                                ans_obj.vote_breakdown = vb

                            q_obj.answer = ans_obj
                            question_objs.append(q_obj)
                            answers_map[q_obj.id] = ans_obj

                        await db.commit()

                        # Check filename collisions within the same job (Requirement 2)
                        computed_docx_name = format_exam_docx_filename(subject_code, exam, platform="fuexam")
                        if computed_docx_name in seen_job_filenames and seen_job_filenames[computed_docx_name] != exam.id:
                            err_msg = (
                                f"Xung đột tên file trong cùng tiến trình: Đề '{exam.title}' (Thread {exam.id}) "
                                f"sinh ra tên file trùng với Thread {seen_job_filenames[computed_docx_name]}: '{computed_docx_name}'. "
                                f"Vui lòng phân biệt hậu tố tiêu đề đề thi."
                            )
                            logger.error(err_msg)
                            raise RuntimeError(err_msg)
                        seen_job_filenames[computed_docx_name] = exam.id

                        # Build .docx for this exam
                        self._broadcast(job_id, {
                            "type": "log",
                            "step": "building_docx",
                            "message": f"Đang xuất file .docx cho đề: {exam.title} ({tot_q} câu)...",
                            "progress": 92,
                        })

                        exam_out_dir = settings.BASE_DIR / "data" / "output" / "FUE" / subject_code
                        exam_out_dir.mkdir(parents=True, exist_ok=True)

                        docx_path = build_exam_docx(
                            subject_code=subject_code,
                            exam=exam,
                            questions=question_objs,
                            output_dir=exam_out_dir,
                            cropped_dir=cropped_dir,
                            platform="fuexam",
                            add_question_number=False,
                            add_divider=True,
                            answers_map=answers_map,
                            ai_status=ai_skipped_reason,
                            fetch_failed_questions=fetch_failed_questions,
                            fetch_failed_details=fetch_failed_details,
                        )

                        all_sources_count["image"] += exam_sources["image"]
                        all_sources_count["comments"] += exam_sources["comments"]
                        all_sources_count["ai"] += exam_sources["ai"]
                        all_sources_count["total"] += tot_q

                        # Read sidecar .meta.json
                        meta_file = exam_out_dir / f"{docx_path.name}.meta.json"
                        meta_info = {}
                        if meta_file.exists():
                            try:
                                meta_info = json.loads(meta_file.read_text(encoding="utf-8"))
                            except Exception:
                                pass

                        rel_output = str(docx_path.resolve().relative_to(settings.BASE_DIR.resolve())).replace("\\", "/")
                        exam_status_val = "completed_with_warnings" if fetch_failed_questions else "completed"
                        file_info = {
                            "filename": docx_path.name,
                            "path": rel_output,
                            "exam_title": exam.title,
                            "thread_id": exam.id,
                            "source_url": exam.url,
                            "questions_count": tot_q,
                            "size_bytes": docx_path.stat().st_size if docx_path.exists() else 0,
                            "cached": False,
                            "cached_at": datetime.now().strftime("%H:%M %d/%m/%Y"),
                            "can_rebuild": True,
                            "platform": "fuexam",
                            "status": exam_status_val,
                            "image_count": meta_info.get("image_count", exam_sources.get("image", 0)),
                            "comment_count": meta_info.get("comment_count", exam_sources.get("comments", 0)),
                            "source_breakdown": meta_info.get("source_breakdown", exam_sources),
                            "confident_count": meta_info.get("confident_count", 0),
                            "weak_count": meta_info.get("weak_count", 0),
                            "conflict_count": meta_info.get("conflict_count", 0),
                            "ai_count": meta_info.get("ai_count", 0),
                            "no_data_count": meta_info.get("no_data_count", 0),
                            "review_needed_questions": meta_info.get("review_needed_questions", []),
                            "image_warnings": meta_info.get("image_warnings", {}),
                            "fetch_failed_questions": meta_info.get("fetch_failed_questions", fetch_failed_questions),
                        }
                        existing_idx = next(
                            (i for i, f in enumerate(created_files) if f.get("thread_id") == exam.id or f.get("filename") == docx_path.name),
                            None,
                        )
                        if existing_idx is not None:
                            created_files[existing_idx] = file_info
                        else:
                            created_files.append(file_info)

                        _upsert_exam_result({
                            "thread_id": exam.id,
                            "exam_title": exam.title,
                            "source_url": exam.url,
                            "filename": docx_path.name,
                            "status": exam_status_val,
                            "fetch_failed_questions": list(fetch_failed_questions),
                            "questions_count": tot_q,
                        })
                        failed_exams = [fe for fe in failed_exams if fe.get("thread_id") != exam.id]

                        job.details = {
                            **job.details,
                            "files": list(created_files),
                            "exam_results": list(exam_results),
                            "failed_exams": list(failed_exams),
                            "completed_exams": exam_idx,
                            "total_exams": total_exams,
                            "answer_sources": all_sources_count,
                        }
                        if not job.result_file_path:
                            job.result_file_path = rel_output
                        await db.commit()

                        self._broadcast(job_id, {
                            "type": "exam_completed",
                            "step": "building_docx",
                            "message": (
                                f"Đã hoàn tất đề {exam.title} (có {len(fetch_failed_questions)} câu lỗi tải bình luận)"
                                if fetch_failed_questions
                                else f"Đã hoàn tất biên soạn đề: {exam.title}"
                            ),
                            "completed_file": file_info,
                            "files": list(created_files),
                            "exam_results": list(exam_results),
                            "failed_exams": list(failed_exams),
                            "answer_sources": all_sources_count,
                            "progress": 95,
                        })

                    except (FuexamAuthError, JobCancelledError, asyncio.CancelledError):
                        raise
                    except Exception as exam_err:
                        await db.rollback()
                        user_msg, err_code, err_retryable = classify_job_error(exam_err)
                        logger.exception(f"[{err_code}] Exam {exam_id_val} ({exam_title_val}) failed in job {job_id}: {exam_err}")
                        fail_entry = {
                            "thread_id": exam_id_val,
                            "exam_title": exam_title_val,
                            "source_url": exam_url_val,
                            "status": "failed",
                            "reason": user_msg,
                            "error_code": err_code,
                            "is_retryable": err_retryable,
                        }
                        _upsert_exam_result(fail_entry)
                        failed_exams = [fe for fe in failed_exams if fe.get("thread_id") != exam_id_val] + [fail_entry]
                        job_res = await db.execute(select(Job).where(Job.job_id == job_id))
                        job = job_res.scalar_one()
                        job.details = {
                            **dict(job.details or {}),
                            "files": list(created_files),
                            "exam_results": list(exam_results),
                            "failed_exams": list(failed_exams),
                            "answer_sources": all_sources_count,
                        }
                        await db.commit()
                        self._broadcast(job_id, {
                            "type": "log",
                            "step": "exam_failed",
                            "message": f"[{exam_idx}/{total_exams}] Đề '{exam_title_val}' lỗi ({err_code}): {user_msg}. Tiếp tục các đề còn lại...",
                            "exam_results": list(exam_results),
                            "failed_exams": list(failed_exams),
                            "progress": max(10, exam_progress_base),
                        })

                crawl_metrics = http_client.get_metrics_summary() if http_client else {}

                # Complete or Fail Job depending on whether any exam succeeded
                if len(created_files) == 0 and len(failed_exams) > 0:
                    first_fail = failed_exams[0]
                    first_reason = first_fail.get("reason", "Không thể biên soạn đề nào.")
                    first_code = first_fail.get("error_code", "ERR-FAILED")
                    first_retryable = bool(first_fail.get("is_retryable", True))
                    job.status = JobStatus.FAILED
                    job.current_step = "failed"
                    job.error_message = (
                        first_reason if len(failed_exams) == 1 else f"Tất cả {len(failed_exams)} đề đều lỗi. {first_reason}"
                    )
                    job.details = {
                        **job.details,
                        "completed_at": datetime.utcnow().isoformat(),
                        "files": created_files,
                        "exam_results": exam_results,
                        "failed_exams": failed_exams,
                        "crawl_metrics": crawl_metrics,
                        "error_code": first_code,
                        "is_retryable": first_retryable,
                        "total_exams": total_exams,
                        "total_questions": total_all_questions,
                        "answer_sources": all_sources_count,
                    }
                    await db.commit()
                    self._broadcast(job_id, {
                        "type": "error",
                        "step": "failed",
                        "message": job.error_message,
                        "error_code": first_code,
                        "is_retryable": first_retryable,
                        "files": created_files,
                        "exam_results": exam_results,
                        "failed_exams": failed_exams,
                        "crawl_metrics": crawl_metrics,
                    })
                    return

                job.status = JobStatus.COMPLETED
                job.current_step = "completed"
                job.progress_percentage = 100.0
                if created_files:
                    job.result_file_path = created_files[0]["path"]
                job.details = {
                    **job.details,
                    "completed_at": datetime.utcnow().isoformat(),
                    "files": created_files,
                    "exam_results": exam_results,
                    "failed_exams": failed_exams,
                    "crawl_metrics": crawl_metrics,
                    "total_exams": total_exams,
                    "total_questions": total_all_questions,
                    "answer_sources": all_sources_count,
                }
                await db.commit()

                summary_msg = f"Hoàn tất biên soạn {len(created_files)}/{total_exams} đề ({total_all_questions} câu hỏi)!"
                if failed_exams:
                    summary_msg = f"Hoàn tất {len(created_files)} đề, {len(failed_exams)} đề lỗi."

                self._broadcast(job_id, {
                    "type": "completed",
                    "step": "completed",
                    "message": summary_msg,
                    "progress": 100,
                    "files": created_files,
                    "exam_results": exam_results,
                    "failed_exams": failed_exams,
                    "crawl_metrics": crawl_metrics,
                    "total_exams": total_exams,
                    "total_questions": total_all_questions,
                    "answer_sources": all_sources_count,
                })
                logger.info(f"Fuexam Job {job_id} completed (files={len(created_files)}, failed={len(failed_exams)}).")

            except (JobCancelledError, asyncio.CancelledError):
                logger.info(f"Fuexam job {job_id} cancelled by user.")
                await db.rollback()
                job.status = JobStatus.FAILED
                job.error_message = "Đã huỷ bởi người dùng"
                job.current_step = "cancelled"
                job.details = {
                    **job.details,
                    "files": list(created_files),
                    "exam_results": list(exam_results),
                    "failed_exams": list(failed_exams),
                    "crawl_metrics": http_client.get_metrics_summary() if http_client else {},
                    "cancelled_at": datetime.utcnow().isoformat(),
                }
                await db.commit()
                self._broadcast(job_id, {
                    "type": "error",
                    "step": "cancelled",
                    "message": "Tiến trình đã bị huỷ bởi người dùng.",
                    "files": list(created_files),
                    "exam_results": list(exam_results),
                    "failed_exams": list(failed_exams),
                })

            except FuexamAuthError as auth_err:
                logger.error(f"Fuexam job {job_id} requires login: {auth_err}")
                job.status = JobStatus.FAILED
                job.error_message = str(auth_err)
                job.current_step = "auth_required"
                job.details = {
                    **job.details,
                    "files": list(created_files),
                    "exam_results": list(exam_results),
                    "failed_exams": list(failed_exams),
                    "failed_at": datetime.utcnow().isoformat(),
                }
                await db.commit()
                self._broadcast(job_id, {
                    "type": "error",
                    "step": "auth_required",
                    "message": str(auth_err),
                    "files": list(created_files),
                })

            except Exception as e:
                user_msg, err_code, is_retryable = classify_job_error(e)
                logger.exception(f"Unexpected error [{err_code}] executing fuexam job {job_id}: {e}")
                job.status = JobStatus.FAILED
                job.error_message = user_msg
                job.current_step = "failed"
                job.completed_at = datetime.utcnow()
                job.details = {
                    **job.details,
                    "error_code": err_code,
                    "is_retryable": is_retryable,
                    "files": list(created_files),
                    "failed_at": datetime.utcnow().isoformat(),
                }
                await db.commit()
                self._broadcast(job_id, {
                    "type": "error",
                    "step": "failed",
                    "message": user_msg,
                    "error_code": err_code,
                    "is_retryable": is_retryable,
                    "files": list(created_files),
                })
            finally:
                if job_id in self._running_tasks:
                    del self._running_tasks[job_id]
                self._cancel_events.pop(job_id, None)


_orchestrator: Optional[JobOrchestrator] = None


def get_orchestrator() -> JobOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = JobOrchestrator()
    return _orchestrator
