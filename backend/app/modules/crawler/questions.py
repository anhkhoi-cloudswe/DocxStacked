import asyncio
import os
import re
from pathlib import Path
from typing import Callable, List, Optional, Tuple
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.db.models import Exam, Question, QuestionType
from backend.app.modules.crawler.browser import AuthenticationRequiredError, get_browser_manager, run_in_browser_thread
from backend.app.modules.crawler.rate_limiter import get_rate_limiter
from backend.app.storage.local import LocalStorage

logger = get_logger(__name__)
settings = get_settings()


def _fetch_thread_html_sync(url: str) -> Tuple[str, Optional[str]]:
    """Fetch HTML of a thread page in worker thread using browser page. Returns (html, status)."""
    bm = get_browser_manager()
    for attempt in range(2):
        try:
            page = bm.get_page()
            resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
            if not resp:
                return "", "error_no_response"
            if resp.status == 403:
                from backend.app.modules.crawler.browser import log_403_diagnostic
                log_403_diagnostic(url, resp, bm._context)
                logger.warning(f"Thread page returned 403 Forbidden: {url}")
                return "", "403_forbidden"
            if resp.status == 200:
                text = page.content()
                if 'data-logged-in="false"' in text and "/login" in page.url:
                    logger.warning(f"Thread page redirected to login: {url}")
                    return "", "unauthenticated"
                return text, "ok"
            return "", f"http_{resp.status}"
        except Exception as e:
            err_name = type(e).__name__
            logger.warning(f"Thread fetch error ({err_name}: {e}) on attempt {attempt + 1}. Re-initializing context...")
            bm.close()
            if attempt == 1:
                return "", f"error_{err_name}: {str(e)}"
    return "", "error_unknown"


def _download_image_sync(
    media_url: Optional[str],
    thumb_url: Optional[str],
    local_path: Path,
) -> Tuple[bool, Optional[str]]:
    """
    Download image synchronously in worker thread using browser page.
    1. In-page fetch from within authenticated page context (carries all session cookies & headers).
    2. Fallback to Playwright element screenshot.
    Returns (success, status_code).
    """
    if not media_url:
        return False, "no_url"

    bm = get_browser_manager()
    for attempt in range(2):
        try:
            page = bm.get_page()
            resp = page.goto(media_url, wait_until="domcontentloaded", timeout=25000)
            if not resp:
                return False, "error_no_response"
            if resp.status == 403:
                from backend.app.modules.crawler.browser import log_403_diagnostic
                log_403_diagnostic(media_url, resp, bm._context)
                logger.warning(f"Media URL returned 403 Forbidden: {media_url}")
                return False, "403_forbidden"
            if "/login" in page.url:
                logger.warning(f"Media URL redirected to login: {media_url}")
                return False, "unauthenticated"

            # Locate media image
            img_loc = page.locator(".js-mediaImage, .xfmgMediaView-image img, img[src*='/full?']").first
            if img_loc.is_visible(timeout=5000):
                src = img_loc.get_attribute("src")
                if src:
                    full_img_url = f"https://fuoverflow.com{src}" if src.startswith("/") else src
                    # Option A: In-page fetch using browser's active session and cookies
                    try:
                        fetch_res = page.evaluate('''async (url) => {
                            try {
                                const resp = await fetch(url);
                                if (!resp.ok) return { ok: false, status: resp.status };
                                const blob = await resp.blob();
                                return new Promise((resolve) => {
                                    const reader = new FileReader();
                                    reader.onloadend = () => resolve({ ok: true, data: reader.result });
                                    reader.readAsDataURL(blob);
                                });
                            } catch (e) {
                                return { ok: false, error: String(e) };
                            }
                        }''', full_img_url)
                        if fetch_res.get("ok") and fetch_res.get("data"):
                            import base64
                            header, b64_data = fetch_res["data"].split(",", 1)
                            raw_bytes = base64.b64decode(b64_data)
                            if len(raw_bytes) > 2000:
                                local_path.parent.mkdir(parents=True, exist_ok=True)
                                with open(local_path, "wb") as f_img:
                                    f_img.write(raw_bytes)
                                logger.debug(f"In-page full-res download succeeded: {len(raw_bytes)} bytes")
                                return True, "ok"
                    except Exception as fetch_err:
                        logger.debug(f"In-page fetch failed: {fetch_err}")

                # Option B: Fallback to high-quality element screenshot
                try:
                    img_loc.screenshot(path=str(local_path))
                    if local_path.exists() and local_path.stat().st_size > 2000:
                        logger.info(f"Screenshot fallback succeeded for {local_path.name}")
                        return True, "ok"
                except Exception as sc_err:
                    logger.error(f"Screenshot fallback failed: {sc_err}")

            return False, "no_image_element"
        except Exception as e:
            err_name = type(e).__name__
            logger.warning(f"Download image error ({err_name}: {e}) on attempt {attempt + 1}...")
            bm.close()
            if attempt == 1:
                return False, f"error_{err_name}: {str(e)}"

    return False, "failed"


async def crawl_exam_questions(
    exam: Exam,
    subject_code: str,
    db: AsyncSession,
    storage: LocalStorage,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> List[Question]:
    """
    Crawl questions for an exam.
    Downloads full-res images using authenticated session.
    Falls back to element screenshot if direct download fails.
    Supports granular resuming:
      - If all questions are already present in DB and on disk, skips network fetch entirely.
      - If partially crawled (e.g. 20/50), resumes from question 21 without re-downloading 1..20.
      - Commits each question progressively so progress is never lost.
    """
    logger.info(f"Crawling questions for exam: {exam.title} ({exam.url})")

    # Prepare storage directory for this exam
    exam_slug = re.sub(r"[^\w\-]", "_", f"exam_{exam.id}_{exam.term or 'fe'}")
    exam_raw_dir = settings.STORAGE_DIR / "raw" / subject_code / exam_slug
    exam_raw_dir.mkdir(parents=True, exist_ok=True)

    # 1. Deduplication / Resume check: if already fully crawled in DB with valid images on disk
    stmt = select(Question).where(Question.exam_id == exam.id).order_by(Question.index)
    res = await db.execute(stmt)
    existing_questions = list(res.scalars().all())

    target_count = exam.question_count or (len(existing_questions) if len(existing_questions) >= 10 else 0)
    if existing_questions and target_count > 0 and len(existing_questions) >= target_count:
        all_valid = True
        for q in existing_questions:
            if not q.local_image_path:
                all_valid = False
                break
            full_path = (
                Path(q.local_image_path)
                if Path(q.local_image_path).is_absolute()
                else settings.BASE_DIR / q.local_image_path
            )
            if not full_path.exists() or full_path.stat().st_size < 8000:
                all_valid = False
                break

        if all_valid:
            logger.info(
                f"Đề '{exam.title}' đã có đầy đủ {len(existing_questions)} câu hỏi và ảnh hợp lệ trên máy. Bỏ qua cào lại."
            )
            if on_progress:
                on_progress(len(existing_questions), len(existing_questions), f"Đã có đủ {len(existing_questions)} câu hỏi")
            return existing_questions

    # 2. Need to crawl or complete missing questions
    rate_limiter = get_rate_limiter()
    await rate_limiter.wait_async()

    # Fetch thread page in dedicated browser worker thread
    thread_html, thread_status = await run_in_browser_thread(_fetch_thread_html_sync, exam.url)
    if thread_status in ("403_forbidden", "unauthenticated"):
        raise AuthenticationRequiredError(
            f"Không thể tải danh sách câu hỏi đề '{exam.title}' ({thread_status}). "
            f"URL: {exam.url}. Hệ thống đã dừng tiến trình và không tính đề này là hoàn tất."
        )
    if not thread_html:
        if thread_status and thread_status.startswith("error_"):
            raise RuntimeError(f"Lỗi nội bộ khi kết nối tải đề thi: {thread_status}")
        logger.error(f"Failed to fetch thread page {exam.url}")
        return existing_questions or []

    soup = BeautifulSoup(thread_html, "html.parser")
    attachment_items = soup.select("section.message-attachments ul.attachmentList li.file")

    if not attachment_items:
        logger.warning(f"No attachment items found in thread {exam.url}")
        return existing_questions or []

    total_items = len(attachment_items)
    exam.question_count = total_items
    logger.info(f"Found {total_items} attachment items in thread '{exam.title}'")

    # Check how many images are already downloaded on disk
    already_downloaded_count = 0
    for idx, item in enumerate(attachment_items, start=1):
        name_el = item.select_one(".file-name")
        file_name = name_el.get_text(strip=True) if name_el else f"Q{idx}.webp"
        q_idx_match = re.search(r"[Qq](\d+)", file_name)
        q_index = int(q_idx_match.group(1)) if q_idx_match else idx
        local_img_filename = f"q{q_index:02d}_{file_name}"
        chk_path = exam_raw_dir / local_img_filename
        if chk_path.exists() and chk_path.stat().st_size > 8000:
            already_downloaded_count += 1

    if already_downloaded_count > 0:
        logger.info(
            f"Đề '{exam.title}': Đã có sẵn {already_downloaded_count}/{total_items} câu hỏi từ phiên trước. "
            f"Tiếp tục tải {total_items - already_downloaded_count} câu còn thiếu..."
        )

    questions: List[Question] = []
    consecutive_auth_fails = 0

    for idx, item in enumerate(attachment_items, start=1):
        name_el = item.select_one(".file-name")
        file_name = name_el.get_text(strip=True) if name_el else f"Q{idx}.webp"

        q_idx_match = re.search(r"[Qq](\d+)", file_name)
        q_index = int(q_idx_match.group(1)) if q_idx_match else idx

        # Extract media link and media_id
        preview_el = item.select_one("a.file-preview")
        sidebar_href = preview_el.get("data-lb-sidebar-href", "") if preview_el else ""
        media_id_match = re.search(r"/media/[^.]+\.(\d+)/", sidebar_href)
        media_id = media_id_match.group(1) if media_id_match else None

        media_url = None
        if sidebar_href:
            media_path = sidebar_href.split("?")[0]
            media_url = f"https://fuoverflow.com{media_path}" if media_path.startswith("/") else media_path

        thumb_img = item.select_one("img[src*='attachments'], img")
        thumb_url = thumb_img.get("src") if thumb_img else None

        local_img_filename = f"q{q_index:02d}_{file_name}"
        local_img_path = exam_raw_dir / local_img_filename
        rel_img_path = str(local_img_path.resolve().relative_to(settings.BASE_DIR.resolve())).replace("\\", "/")

        # Check existing Question in DB
        stmt = select(Question).where(Question.exam_id == exam.id, Question.index == q_index)
        res = await db.execute(stmt)
        question = res.scalar_one_or_none()

        # Check if already downloaded on disk (Resume feature - require full-res >8KB)
        already_downloaded = local_img_path.exists() and local_img_path.stat().st_size > 8000

        if not already_downloaded:
            logger.info(f"Đang tải ảnh câu Q{q_index} ({idx}/{total_items}): {file_name}...")
            await rate_limiter.wait_async()
            # Run image download in dedicated browser worker thread
            dl_ok, dl_status = await run_in_browser_thread(_download_image_sync, media_url, thumb_url, local_path=local_img_path)
            if dl_status in ("403_forbidden", "unauthenticated"):
                raise AuthenticationRequiredError(
                    f"Tải ảnh câu {q_index} ({file_name}) thất bại do máy chủ từ chối truy cập ({dl_status}). "
                    f"URL: {media_url}. Hệ thống đã dừng tiến trình và không tính câu này là hoàn tất."
                )
            if not dl_ok or not local_img_path.exists() or local_img_path.stat().st_size <= 8000:
                raise RuntimeError(
                    f"Tải ảnh câu {q_index} ({file_name}) không thành công (kích thước file không hợp lệ hoặc thiếu ảnh)."
                )

            if on_progress:
                on_progress(idx, total_items, f"Đã tải {file_name}")
        else:
            consecutive_auth_fails = 0
            logger.debug(f"Q{q_index} đã có sẵn ({file_name}), bỏ qua tải lại.")
            if on_progress:
                on_progress(idx, total_items, f"Đã có sẵn {file_name}")

        if not question:
            question = Question(
                exam_id=exam.id,
                index=q_index,
                file_name=file_name,
                local_image_path=rel_img_path if local_img_path.exists() else None,
                media_url=media_url,
                media_id=media_id,
                qtype=QuestionType.SINGLE,
            )
            db.add(question)
        else:
            if local_img_path.exists():
                question.local_image_path = rel_img_path
            if media_url:
                question.media_url = media_url
            if media_id:
                question.media_id = media_id

        # Commit progressively so every question is persisted immediately
        await db.commit()
        questions.append(question)

    logger.info(f"Completed processing {len(questions)}/{total_items} questions for exam {exam.title}")
    return questions
