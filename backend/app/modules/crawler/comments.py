import asyncio
import hashlib
from pathlib import Path
import re
from typing import Callable, Dict, List, Optional, Tuple
from bs4 import BeautifulSoup
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.db.models import Comment, Exam, Question
from backend.app.modules.crawler.browser import AuthenticationRequiredError, get_browser_manager
from backend.app.modules.crawler.rate_limiter import get_rate_limiter
from backend.app.storage.local import LocalStorage

logger = get_logger(__name__)
settings = get_settings()


def _fetch_media_html_sync(url: str) -> Tuple[str, Optional[str]]:
    """
    Fetch HTML of a media detail page in worker thread using persistent browser context.
    Returns (html_text, status_reason).
    """
    bm = get_browser_manager()
    try:
        ctx = bm.start_context(headless=True)
        resp = ctx.request.get(url, timeout=25000)
    except Exception as e:
        logger.warning(f"Media fetch error ({e}). Retrying with fresh browser context...")
        bm.close()
        ctx = bm.start_context(headless=True)
        resp = ctx.request.get(url, timeout=25000)
    if resp.status == 403:
        logger.warning(f"Media page returned 403 Forbidden: {url}")
        return "", "403_forbidden"
    if resp.status == 200:
        text = resp.text()
        if 'data-logged-in="false"' in text or "/login" in resp.url:
            logger.warning(f"Media page returned 200 but not authenticated or redirected to login: {url}")
            return "", "unauthenticated"
        return text, "ok"
    else:
        logger.warning(f"Failed to fetch media page {url}, status: {resp.status}")
        return "", f"http_{resp.status}"


def parse_comments_from_html(
    html_str: str,
    question_id: int,
    html_path: Optional[str] = None,
) -> List[Comment]:
    """
    Parse comment elements from XenForo Media Gallery HTML.
    Extracts:
      - comment_id (string ID)
      - author_hash (SHA-256 hash to respect privacy)
      - raw_text (excluding blockquote contents to avoid duplicate answer attribution)
      - upvotes (reactions count from .reactionsBar)
      - is_reply (boolean)
      - quoted_comment_id (integer ID of parent comment if quoted)
      - html_path (relative path to saved raw HTML)
    """
    soup = BeautifulSoup(html_str, "html.parser")
    comment_els = soup.select(".message--comment, .message--mediaComment, .js-comment")
    comments: List[Comment] = []

    for c in comment_els:
        # 1. Comment ID
        raw_id = c.get("data-content") or c.get("id") or ""
        m_id = re.search(r"\d+", raw_id)
        comment_id = m_id.group(0) if m_id else None

        # 2. Author and hash
        author_el = c.select_one(".message-name, .comment-user, .username, .comment-author")
        author_name = author_el.get_text(strip=True) if author_el else "Unknown"
        author_hash = hashlib.sha256(author_name.encode("utf-8")).hexdigest()[:16]

        # 3. Reactions / Upvotes count
        rx_bar = c.select_one(".reactionsBar")
        upvotes = 0
        if rx_bar and ("is-active" in rx_bar.get("class", []) or rx_bar.select(".reaction-image, .reaction")):
            rx_text = rx_bar.get_text(" ", strip=True)
            # Count named <bdi> users
            bdis = rx_bar.select("a.reactionsBar-link bdi, .reactionsBar bdi")
            named_count = len(bdis)

            # Match 'and N others' or 'và N người khác'
            m_others = re.search(r"(?:and|và)\s+(\d+)\s+(?:others|người khác)", rx_text, re.IGNORECASE)
            others_count = int(m_others.group(1)) if m_others else 0

            # Match total count explicitly if present
            m_total = re.search(r"(\d+)\s+(?:reactions|lượt thích|phản ứng)", rx_text, re.IGNORECASE)
            if m_total:
                upvotes = int(m_total.group(1))
            elif named_count > 0 or others_count > 0:
                upvotes = named_count + others_count
            else:
                icons = len(rx_bar.select(".reaction-image, .reaction[data-reaction-id]"))
                upvotes = max(icons, 1)

        # 4. Quoted Comment ID & is_reply
        quoted_comment_id = None
        is_reply = False

        quote_block = c.select_one("blockquote, .bbCodeBlock--quote")
        if quote_block:
            is_reply = True
            title_link = quote_block.select_one(".bbCodeBlock-title a")
            if title_link and title_link.get("href"):
                m_q = re.search(r"/comments/(\d+)", title_link.get("href"))
                if m_q:
                    quoted_comment_id = int(m_q.group(1))

        if not quoted_comment_id and c.select_one(".comment--reply, .message--response"):
            is_reply = True

        # 5. Clean text: remove blockquotes before extracting commenter's text
        bb = c.select_one(".message-body .bbWrapper, .message-body, .comment-content")
        raw_text = ""
        if bb:
            bb_copy = BeautifulSoup(str(bb), "html.parser").find()
            for qb in bb_copy.select("blockquote, .bbCodeBlock--quote"):
                qb.decompose()
            raw_text = bb_copy.get_text(" ", strip=True)

        if not raw_text and not comment_id:
            continue

        comment_obj = Comment(
            question_id=question_id,
            comment_id=comment_id,
            author_hash=author_hash,
            raw_text=raw_text,
            upvotes=upvotes,
            is_reply=is_reply,
            quoted_comment_id=quoted_comment_id,
            html_path=html_path,
        )
        comments.append(comment_obj)

    return comments


async def crawl_question_comments(
    question: Question,
    subject_code: str,
    exam_slug: str,
    db: AsyncSession,
    storage: Optional[LocalStorage] = None,
    force_refresh: bool = False,
) -> List[Comment]:
    """
    Crawl comments for a single question:
      - Uses resume logic: returns existing comments in DB if present and not force_refresh.
      - Loads cached raw HTML if present on disk.
      - Fetches via authenticated Playwright session with rate limiting if not cached.
      - Saves raw HTML to data/raw/{subject_code}/{exam_slug}/comments/q{index:03d}_{media_id}.html.
      - Parses comments (reactions, quotes, stripped text) and syncs to SQLite DB.
    """
    if not question.media_url and not question.media_id:
        logger.warning(f"Question Q{question.index} has no media_url or media_id, skipping comments.")
        return []

    # 1. DB cache check (Resume feature)
    if not force_refresh:
        stmt = select(Comment).where(Comment.question_id == question.id)
        res = await db.execute(stmt)
        existing_cmts = list(res.scalars().all())
        if existing_cmts:
            logger.debug(f"Q{question.index}: Đã có {len(existing_cmts)} bình luận trong CSDL. Bỏ qua cào lại.")
            return existing_cmts

    media_url = question.media_url
    if not media_url:
        media_url = f"https://fuoverflow.com/media/{question.media_id}/"

    # Define raw HTML storage path
    media_id_str = str(question.media_id or "unknown")
    comments_dir = settings.STORAGE_DIR / "raw" / subject_code / exam_slug / "comments"
    comments_dir.mkdir(parents=True, exist_ok=True)
    html_file = comments_dir / f"q{question.index:03d}_{media_id_str}.html"
    rel_html_path = str(html_file.resolve().relative_to(settings.BASE_DIR.resolve())).replace("\\", "/")

    html_content = ""

    # Resume check: load from existing raw HTML if valid
    if not force_refresh and html_file.exists() and html_file.stat().st_size > 500:
        try:
            html_content = html_file.read_text(encoding="utf-8")
            logger.debug(f"Resuming comments for Q{question.index} from cached HTML: {html_file.name}")
        except Exception as read_err:
            logger.warning(f"Failed to read cached HTML {html_file}: {read_err}")

    # Fetch from web if not cached or force_refresh
    if not html_content:
        rate_limiter = get_rate_limiter()
        await rate_limiter.wait_async()

        logger.info(f"Fetching comments from web for Q{question.index} ({media_url})...")
        html_content, html_status = await asyncio.to_thread(_fetch_media_html_sync, media_url)
        if html_status in ("403_forbidden", "unauthenticated"):
            raise AuthenticationRequiredError(
                "Phiên đăng nhập FUOverflow đã bị ngắt hoặc hết hạn (do diễn đàn chỉ cho phép 1 phiên đăng nhập hoạt động cùng lúc). "
                "Vui lòng đăng nhập lại và bấm 'Chạy tiếp từ chỗ dừng'!"
            )

        if html_content:
            try:
                html_file.write_text(html_content, encoding="utf-8")
                logger.debug(f"Saved raw comments HTML to {html_file}")
            except Exception as write_err:
                logger.warning(f"Failed to write raw HTML {html_file}: {write_err}")

    if not html_content:
        logger.warning(f"Could not retrieve comments HTML for Q{question.index}")
        return []

    # Parse comments from HTML
    parsed_comments = parse_comments_from_html(
        html_str=html_content,
        question_id=question.id,
        html_path=rel_html_path,
    )

    # Sync to DB: remove old comments for this question and insert newly parsed
    await db.execute(delete(Comment).where(Comment.question_id == question.id))
    for cmt in parsed_comments:
        db.add(cmt)

    await db.commit()
    logger.info(f"Q{question.index}: Synced {len(parsed_comments)} comments to database.")
    return parsed_comments


async def crawl_exam_comments(
    exam: Exam,
    subject_code: str,
    db: AsyncSession,
    storage: Optional[LocalStorage] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    force_refresh: bool = False,
) -> List[Comment]:
    """
    Crawl comments for all questions in an exam with rate limiting, resume, and progress callback.
    - If all questions already have comments in DB and not force_refresh, skips crawling instantly.
    """
    logger.info(f"Crawling comments for exam: {exam.title} (ID {exam.id})...")

    # Fetch all questions for this exam
    stmt = select(Question).where(Question.exam_id == exam.id).order_by(Question.index)
    res = await db.execute(stmt)
    questions = list(res.scalars().all())

    if not questions:
        logger.warning(f"No questions found for exam {exam.id} ({exam.title})")
        return []

    # Deduplication check: if all questions already have comments in DB
    q_ids = [q.id for q in questions]
    cmt_count_stmt = (
        select(Comment.question_id, func.count(Comment.id))
        .where(Comment.question_id.in_(q_ids))
        .group_by(Comment.question_id)
    )
    cmt_res = await db.execute(cmt_count_stmt)
    q_with_cmts = dict(cmt_res.all())

    if not force_refresh and len(q_with_cmts) == len(questions):
        logger.info(
            f"Đề '{exam.title}': Đã có đầy đủ bình luận cho tất cả {len(questions)}/{len(questions)} câu hỏi trong CSDL. Bỏ qua cào lại bình luận."
        )
        if on_progress:
            on_progress(len(questions), len(questions), f"Đã có đủ bình luận {len(questions)} câu")
        existing_all = (
            await db.execute(select(Comment).where(Comment.question_id.in_(q_ids)))
        ).scalars().all()
        return list(existing_all)

    exam_slug = re.sub(r"[^\w\-]", "_", f"exam_{exam.id}_{exam.term or 'fe'}")
    all_comments: List[Comment] = []
    total = len(questions)

    for i, q in enumerate(questions, start=1):
        q_comments = await crawl_question_comments(
            question=q,
            subject_code=subject_code,
            exam_slug=exam_slug,
            db=db,
            storage=storage,
            force_refresh=force_refresh,
        )
        all_comments.extend(q_comments)

        if on_progress:
            on_progress(i, total, f"Q{q.index}: {len(q_comments)} comments")

    logger.info(f"Finished crawling comments for exam {exam.title}: {len(all_comments)} comments total across {total} questions.")
    return all_comments

