import asyncio
import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.db.models import Answer, Comment, ExamType, Job, JobStatus, Question, Subject
from backend.app.db.session import async_session_factory
from backend.app.modules.analysis.ai_check import get_ai_check_service
from backend.app.modules.analysis.voting import tally_votes
from backend.app.modules.settings.service import get_active_settings
from backend.app.modules.crawler.browser import AuthenticationRequiredError, get_browser_manager
from backend.app.modules.crawler.comments import crawl_exam_comments
from backend.app.modules.crawler.exams import crawl_subject_exams
from backend.app.modules.crawler.questions import crawl_exam_questions
from backend.app.modules.crawler.subjects import get_or_fetch_subjects
from backend.app.modules.export.docx_builder import build_exam_docx, build_merged_docx, format_exam_docx_filename
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
        "image_width_cm": float(export_cfg.get("image_width_cm", 16.51)),
        "image_zoom_percent": int(export_cfg.get("image_zoom_percent", 100)),
        "highlight_low_confidence": bool(export_cfg.get("highlight_low_confidence", True)),
        "show_question_number": bool(export_cfg.get("show_question_number", True)),
        "show_separator_line": bool(export_cfg.get("show_separator_line", True)),
        "ai_enabled": bool(ai_cfg.get("enabled", True)),
    }
    return hashlib.sha256(json.dumps(key_data, sort_keys=True).encode("utf-8")).hexdigest()[:16]


class JobOrchestrator:
    """
    Orchestrates exam compilation jobs and SSE progress broadcasting.
    """

    def __init__(self):
        self._listeners: Dict[str, List[asyncio.Queue]] = {}
        self._event_history: Dict[str, List[Dict[str, Any]]] = {}
        self._running_tasks: Dict[str, asyncio.Task] = {}
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
    ) -> Job:
        """Create and launch a background exam compilation job."""
        job_uuid = str(uuid.uuid4())

        async with async_session_factory() as db:
            active_cfg = await get_active_settings(db, job_options={"crawl": {"default_count": limit}})
            job = Job(
                job_id=job_uuid,
                subject_code=subject_code.upper(),
                exam_type=exam_type,
                exam_count=limit,
                status=JobStatus.PENDING,
                current_step="init",
                progress_percentage=0.0,
                config_snapshot=active_cfg,
                details={
                    "subject_code": subject_code.upper(),
                    "exam_type": exam_type.value,
                    "limit": limit,
                    "force_refresh": force_refresh,
                },
            )
            db.add(job)
            await db.commit()
            await db.refresh(job)

        self._event_history[job_uuid] = []
        task = asyncio.create_task(
            self._run_job_pipeline(job_uuid, subject_code.upper(), exam_type, limit, force_refresh)
        )
        self._running_tasks[job_uuid] = task
        return job

    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a running or pending job."""
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
                self._broadcast(job_id, {"type": "error", "message": "Tiến trình đã bị huỷ bởi người dùng."})
                return True
        return False

    async def resume_job(self, job_id: str) -> Optional[Job]:
        """Resume a stopped or failed job from its last completed state."""
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
        task = asyncio.create_task(
            self._run_job_pipeline(job.job_id, job.subject_code, job.exam_type, job.exam_count, force_ref)
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
    ):
        """Execute the compilation pipeline step-by-step."""
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
                    is_auth = await asyncio.to_thread(bm.ensure_logged_in, 30, True)
                    if not is_auth:
                        raise AuthenticationRequiredError("Phiên đăng nhập hết hạn hoặc chưa xác thực")
                except AuthenticationRequiredError as auth_err:
                    error_msg = "Cần đăng nhập lại: phiên đăng nhập hết hạn hoặc chưa xác thực"
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
                    cached_filename = format_exam_docx_filename(subject_code, exam)
                    cached_path = settings.STORAGE_DIR / "output" / subject_code / cached_filename
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
                            except Exception:
                                pass
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
                        file_info = {
                            "filename": cached_path.name,
                            "path": rel_output,
                            "exam_title": exam.title,
                            "questions_count": len(existing_questions),
                            "size_bytes": cached_path.stat().st_size,
                            "cached": True,
                            "cached_at": cached_time_str,
                            "can_rebuild": True,
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
                    ai_weight = float(job_cfg.get("voting", {}).get("ai_weight", 1.0))

                    for q in questions:
                        await db.refresh(q, ["comments", "answer"])

                        ai_votes = []
                        ai_options = {}
                        img_path = getattr(q, "local_image_path", None)
                        if ai_enabled and img_path and ai_service.is_available():
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

                        voting_res = tally_votes(
                            q.comments,
                            ai_votes=ai_votes if ai_votes else None,
                            ai_weight=ai_weight,
                        )

                        breakdown = dict(voting_res.vote_breakdown)
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

                    docx_path = build_exam_docx(
                        subject_code=subject_code,
                        exam=exam,
                        questions=questions,
                        answer_format=ans_fmt,
                        highlight_check_needed=job_cfg.get("export", {}).get("highlight_low_confidence", True),
                        add_divider=job_cfg.get("export", {}).get("show_separator_line", True),
                        add_question_number=job_cfg.get("export", {}).get("show_question_number", True),
                    )

                    # Save sidecar metadata for cache invalidation
                    now_dt = datetime.now()
                    meta_data = {
                        "settings_hash": current_settings_hash,
                        "created_at": now_dt.isoformat(),
                        "created_at_epoch": now_dt.timestamp(),
                        "created_at_formatted": now_dt.strftime("%H:%M %d/%m/%Y"),
                        "latest_comment_timestamp": latest_comment_ts,
                        "questions_count": len(questions),
                        "exam_title": exam.title,
                    }
                    meta_path = docx_path.with_name(docx_path.name + ".meta.json")
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
                    merged_docx_path = build_merged_docx(
                        subject_code=subject_code,
                        exams_data=all_exam_question_pairs,
                        answer_format=ans_fmt,
                        highlight_check_needed=job_cfg.get("export", {}).get("highlight_low_confidence", True),
                        add_divider=job_cfg.get("export", {}).get("show_separator_line", True),
                        add_question_number=job_cfg.get("export", {}).get("show_question_number", True),
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
                logger.exception(f"Unexpected error executing job {job_id}: {e}")
                job.status = JobStatus.FAILED
                job.error_message = str(e)
                job.current_step = "failed"
                job.completed_at = datetime.utcnow()
                job.details = {
                    **job.details,
                    "files": list(created_files),
                    "failed_at": datetime.utcnow().isoformat(),
                }
                await db.commit()
                self._broadcast(job_id, {
                    "type": "error",
                    "step": "failed",
                    "message": f"Lỗi trong quá trình xử lý: {str(e)}",
                    "files": list(created_files),
                })
            finally:
                if job_id in self._running_tasks:
                    del self._running_tasks[job_id]


_orchestrator: Optional[JobOrchestrator] = None


def get_orchestrator() -> JobOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = JobOrchestrator()
    return _orchestrator
