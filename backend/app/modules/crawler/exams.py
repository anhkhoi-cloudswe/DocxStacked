import asyncio
from datetime import datetime
import re
from typing import List, Optional
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.db.models import Exam, ExamType, Subject
from backend.app.modules.crawler.browser import get_browser_manager
from backend.app.modules.crawler.rate_limiter import get_rate_limiter

logger = get_logger(__name__)
settings = get_settings()


def _fetch_url_html(url: str) -> str:
    """Synchronous fetcher executed in worker thread to prevent Playwright Sync API in asyncio errors."""
    bm = get_browser_manager()
    try:
        ctx = bm.start_context(headless=True)
        resp = ctx.request.get(url, timeout=30000)
    except Exception as e:
        logger.warning(f"Exam url fetch error ({e}). Retrying with fresh browser context...")
        bm.close()
        ctx = bm.start_context(headless=True)
        resp = ctx.request.get(url, timeout=30000)
    return resp.text() if resp.status == 200 else ""


async def crawl_subject_exams(
    subject: Subject,
    exam_type: ExamType = ExamType.FE,
    limit: int = 4,
    db: Optional[AsyncSession] = None,
) -> List[Exam]:
    """
    Crawl exam threads for a given subject from fuoverflow.com.
    Filters threads by exam_type (FE vs PE).
    Limits to `limit` exams.
    """
    logger.info(f"Crawling {exam_type.value} exams for subject {subject.code} (limit={limit})...")

    # If DB already has enough exams for this subject, use them first
    if db is not None:
        res = await db.execute(select(Exam).where(Exam.subject_id == subject.id, Exam.exam_type == exam_type))
        existing = list(res.scalars().all())
        if len(existing) >= limit:
            logger.info(f"Found {len(existing)} existing exams in DB for {subject.code}")
            return existing[:limit]

    forum_url = subject.forum_url or f"https://fuoverflow.com/forums/{subject.code}/"
    rate_limiter = get_rate_limiter()
    await rate_limiter.wait_async()

    # Run browser request in worker thread
    html = await asyncio.to_thread(_fetch_url_html, forum_url)
    if not html:
        logger.error(f"Failed to fetch forum URL {forum_url}")
        # Fallback to any existing exams in DB
        if db is not None:
            res = await db.execute(select(Exam).where(Exam.subject_id == subject.id, Exam.exam_type == exam_type))
            existing = list(res.scalars().all())
            if existing:
                logger.info(f"Fallback to {len(existing)} existing exams in DB for {subject.code}")
                return existing[:limit]
        return []

    soup = BeautifulSoup(html, "html.parser")
    thread_items = soup.select(".structItemContainer .structItem--thread")
    logger.info(f"Found {len(thread_items)} total threads in {subject.code}")

    found_exams: List[Exam] = []

    for item in thread_items:
        if len(found_exams) >= limit:
            break

        # Check title & link
        title_el = item.select_one(".structItem-title a[href^='/threads/']:not([href$='/latest'])")
        if not title_el:
            continue

        raw_title = title_el.get_text(strip=True)
        href = title_el.get("href", "")
        thread_url = f"https://fuoverflow.com{href}" if href.startswith("/") else href

        # Extract thread ID and slug
        thread_id_match = re.search(r"\.(\d+)/?$", href)
        thread_id = thread_id_match.group(1) if thread_id_match else None

        # Check label prefix
        badge_el = item.select_one(".label")
        badge_text = badge_el.get_text(strip=True).upper() if badge_el else ""

        # Determine if FE or PE
        is_fe = "FE" in badge_text or "RE" in badge_text or "-fe." in href.lower() or "-re." in href.lower() or "fe" in raw_title.lower() or "re" in raw_title.lower()
        is_pe = "PE" in badge_text or "-pe-" in href.lower() or "-pe." in href.lower() or "pe" in raw_title.lower()

        if is_fe:
            detected_type = ExamType.FE
        elif is_pe:
            detected_type = ExamType.PE
        else:
            continue

        if detected_type != exam_type:
            continue

        # Extract post date
        date_el = item.select_one(".structItem-startDate time, .structItem-cell--main time")
        post_date = None
        if date_el and date_el.get("datetime"):
            try:
                # datetime attribute e.g. 2026-08-01T23:43:45+0700
                post_date = datetime.fromisoformat(date_el["datetime"])
            except Exception:
                post_date = None

        # Extract question count from thread title e.g. '40 câu', '50 questions' or meta
        q_count = 0
        q_match = re.search(r"(\d+)\s*(?:câu|cau|questions?)\b", raw_title, re.IGNORECASE)
        if q_match:
            q_count = int(q_match.group(1))
        elif is_fe:
            # Default FE exams at FPT have standard 40 or 50 questions
            q_count = 40

        # Check if exam already exists in DB
        exam = None
        if db:
            stmt = select(Exam).where(Exam.subject_id == subject.id, Exam.url == thread_url)
            res = await db.execute(stmt)
            exam = res.scalar_one_or_none()

        # Extract term (e.g. SU26, FA24, SP25)
        term_match = re.search(r"\b(SU|FA|SP|WI)\s*(\d{2,4})\b", raw_title, re.IGNORECASE)
        term = None
        if term_match:
            season = term_match.group(1).upper()
            yr_str = term_match.group(2)
            yr_short = yr_str[-2:] if len(yr_str) == 4 else yr_str
            term = f"{season}{yr_short}"

        if not exam:
            exam = Exam(
                subject_id=subject.id,
                title=raw_title,
                url=thread_url,
                exam_type=detected_type,
                term=term,
                post_date=post_date,
                question_count=q_count,
            )
            if db:
                db.add(exam)
                await db.flush()
        else:
            # Update missing attributes if needed
            if not exam.post_date and post_date:
                exam.post_date = post_date
            if not exam.term and term:
                exam.term = term
            if (not exam.question_count or exam.question_count == 0) and q_count > 0:
                exam.question_count = q_count

        found_exams.append(exam)

    if db:
        await db.commit()

    logger.info(f"Retrieved {len(found_exams)} matching {exam_type.value} exams for {subject.code}")
    return found_exams
