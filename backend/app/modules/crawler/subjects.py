import asyncio
from datetime import datetime
import re
from typing import Any, Dict, List, Optional
import unicodedata
from bs4 import BeautifulSoup
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import get_settings
from backend.app.core.logging import get_logger
from backend.app.db.models import Subject
from backend.app.modules.crawler.browser import get_browser_manager
from backend.app.modules.crawler.rate_limiter import get_rate_limiter

logger = get_logger(__name__)
settings = get_settings()

KNOWN_POPULAR_SUBJECTS = [
    {"code": "CSD202", "name": "Cấu trúc dữ liệu và giải thuật (CSD202)", "url": "https://fuoverflow.com/forums/CSD202/"},
    {"code": "PRN211", "name": "Lập trình đa nền tảng với .NET (PRN211)", "url": "https://fuoverflow.com/forums/PRN211/"},
    {"code": "PRN212", "name": "Lập trình ứng dụng .NET nâng cao (PRN212)", "url": "https://fuoverflow.com/forums/PRN212/"},
    {"code": "PRN221", "name": "Lập trình ứng dụng đa nền tảng .NET (PRN221)", "url": "https://fuoverflow.com/forums/PRN221/"},
    {"code": "PRN231", "name": "Xây dựng Web API với .NET (PRN231)", "url": "https://fuoverflow.com/forums/PRN231/"},
    {"code": "PRN232", "name": "Xây dựng ứng dụng web với .NET (PRN232)", "url": "https://fuoverflow.com/forums/PRN232/"},
    {"code": "PRM392", "name": "Lập trình ứng dụng di động Android (PRM392)", "url": "https://fuoverflow.com/forums/PRM392/"},
    {"code": "PRM393", "name": "Lập trình ứng dụng di động (PRM393)", "url": "https://fuoverflow.com/forums/PRM393/"},
    {"code": "SWD392", "name": "Kiến trúc và thiết kế phần mềm (SWD392)", "url": "https://fuoverflow.com/forums/SWD392/"},
    {"code": "SWE102", "name": "Nhập môn Kỹ thuật Phần mềm (SWE102)", "url": "https://fuoverflow.com/forums/SWE102/"},
    {"code": "SWP391", "name": "Dự án phát triển ứng dụng (SWP391)", "url": "https://fuoverflow.com/forums/SWP391/"},
    {"code": "SWT301", "name": "Kiểm thử phần mềm (SWT301)", "url": "https://fuoverflow.com/forums/SWT301/"},
    {"code": "VNR202", "name": "Lịch sử Đảng Cộng sản Việt Nam (VNR202)", "url": "https://fuoverflow.com/forums/VNR202/"},
    {"code": "MLN111", "name": "Triết học Mác - Lênin (MLN111)", "url": "https://fuoverflow.com/forums/MLN111/"},
    {"code": "MLN122", "name": "Kinh tế chính trị Mác - Lênin (MLN122)", "url": "https://fuoverflow.com/forums/MLN122/"},
    {"code": "MLN131", "name": "Chủ nghĩa xã hội khoa học (MLN131)", "url": "https://fuoverflow.com/forums/MLN131/"},
    {"code": "HCM202", "name": "Tư tưởng Hồ Chí Minh (HCM202)", "url": "https://fuoverflow.com/forums/HCM202/"},
    {"code": "DBI202", "name": "Hệ cơ sở dữ liệu (DBI202)", "url": "https://fuoverflow.com/forums/DBI202/"},
    {"code": "MAS291", "name": "Xác suất thống kê (MAS291)", "url": "https://fuoverflow.com/forums/MAS291/"},
    {"code": "MAD101", "name": "Toán rời rạc (MAD101)", "url": "https://fuoverflow.com/forums/MAD101/"},
    {"code": "MAE101", "name": "Toán cho khối kỹ thuật (MAE101)", "url": "https://fuoverflow.com/forums/MAE101/"},
    {"code": "PRO192", "name": "Lập trình hướng đối tượng Java (PRO192)", "url": "https://fuoverflow.com/forums/PRO192/"},
    {"code": "PRF192", "name": "Nhập môn lập trình C (PRF192)", "url": "https://fuoverflow.com/forums/PRF192/"},
    {"code": "PRF193", "name": "Nhập môn lập trình (PRF193)", "url": "https://fuoverflow.com/forums/PRF193/"},
    {"code": "CEA201", "name": "Tổ chức và kiến trúc máy tính (CEA201)", "url": "https://fuoverflow.com/forums/CEA201/"},
    {"code": "CSI104", "name": "Nhập môn Khoa học Máy tính (CSI104)", "url": "https://fuoverflow.com/forums/CSI104/"},
    {"code": "CSI105", "name": "Nhập môn Khoa học Máy tính (CSI105)", "url": "https://fuoverflow.com/forums/CSI105/"},
    {"code": "OSG203", "name": "Hệ điều hành (OSG203)", "url": "https://fuoverflow.com/forums/OSG203/"},
    {"code": "NWC203", "name": "Mạng máy tính (NWC203)", "url": "https://fuoverflow.com/forums/NWC203/"},
    {"code": "IOT102", "name": "Nhập môn Internet vạn vật IoT (IOT102)", "url": "https://fuoverflow.com/forums/IOT102/"},
    {"code": "WED201C", "name": "Thiết kế Web (WED201c)", "url": "https://fuoverflow.com/forums/WED201C/"},
    {"code": "SSG104", "name": "Kỹ năng làm việc nhóm và giao tiếp (SSG104)", "url": "https://fuoverflow.com/forums/SSG104/"},
    {"code": "JPD113", "name": "Tiếng Nhật sơ cấp 1 (JPD113)", "url": "https://fuoverflow.com/forums/JPD113/"},
    {"code": "JPD123", "name": "Tiếng Nhật sơ cấp 2 (JPD123)", "url": "https://fuoverflow.com/forums/JPD123/"},
    {"code": "ACC101", "name": "Nguyên lý kế toán (ACC101)", "url": "https://fuoverflow.com/forums/ACC101/"},
    {"code": "FIN307", "name": "Thị trường và định chế tài chính (FIN307)", "url": "https://fuoverflow.com/forums/FIN307/"},
    {"code": "MKT101", "name": "Marketing căn bản (MKT101)", "url": "https://fuoverflow.com/forums/MKT101/"},
    {"code": "ECO111", "name": "Kinh tế vi mô (ECO111)", "url": "https://fuoverflow.com/forums/ECO111/"},
]

KNOWN_NAMES_MAP = {s["code"].upper(): s["name"] for s in KNOWN_POPULAR_SUBJECTS}

NON_SUBJECT_SLUGS = {
    "tong-hop",
    "quy-dinh",
    "huong-dan-dang-tai-lieu",
    "thao-luan-chung",
    "gop-y",
    "categories",
    "forums",
    "rss",
    "-",
}


def strip_vietnamese_accents(text: str) -> str:
    """Normalize and strip Vietnamese diacritics for accent-insensitive search."""
    if not text:
        return ""
    text = text.replace("đ", "d").replace("Đ", "D")
    normalized = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in normalized if unicodedata.category(c) != "Mn")
    return stripped.lower().strip()


def parse_subjects_from_category_html(html: str) -> List[Dict[str, str]]:
    """Parse subject codes and forum links from FuOverflow /categories/subjects/ HTML."""
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    found_map: Dict[str, Dict[str, str]] = {}

    # Target subNodeLinks and node-title links
    links = soup.select(".subNodeLink--forum, a[href*='/forums/']")
    for a in links:
        href = a.get("href", "")
        # Extract forum slug e.g. /forums/CSD202/ or /forums/CSD202.123/
        match = re.search(r"/forums/([A-Za-z0-9_\-]+)(?:\.\d+)?/?", href)
        if not match:
            continue

        raw_slug = match.group(1).strip()
        slug_lower = raw_slug.lower()
        if slug_lower in NON_SUBJECT_SLUGS or raw_slug in ("-", "RSS") or len(raw_slug) < 2:
            continue
        # Reject non-alphanumeric codes like TRANS-4, TRANS-5, TRANS-6 or RSS links
        if not re.match(r"^[A-Za-z0-9_]{2,15}$", raw_slug) or raw_slug.startswith("TRANS-"):
            continue

        code = raw_slug.upper()
        # Clean text
        text = a.get_text(strip=True)
        # Skip RSS text
        if text.upper() == "RSS" or text == "-":
            continue
        # Check if text has full name like "CSD202 - Cấu trúc dữ liệu"
        name = text
        if " - " in text:
            parts = text.split(" - ", 1)
            if parts[0].strip().upper() == code:
                name = parts[1].strip()

        # If name is just the code, check our known name mappings
        if name.upper() == code and code in KNOWN_NAMES_MAP:
            name = KNOWN_NAMES_MAP[code]

        full_url = f"https://fuoverflow.com/forums/{raw_slug}/" if not href.startswith("http") else href

        if code not in found_map:
            found_map[code] = {
                "code": code,
                "name": name,
                "forum_url": full_url,
            }
        else:
            # If current existing has short name and new one has descriptive name, upgrade
            if found_map[code]["name"] == code and name != code:
                found_map[code]["name"] = name

    # Sort alphabetically by code
    return sorted(found_map.values(), key=lambda s: s["code"])


def _fetch_url_sync(url: str) -> str:
    """Fetch URL synchronously via Playwright context in worker thread."""
    bm = get_browser_manager()
    ctx = bm.start_context(headless=True)
    resp = ctx.request.get(url, timeout=30000)
    return resp.text() if resp.status == 200 else ""


async def sync_subjects_from_web(
    db: AsyncSession,
    html: Optional[str] = None,
) -> Dict[str, Any]:
    """Crawl FuOverflow category page and upsert all discovered subjects."""
    if html is None:
        category_url = "https://fuoverflow.com/categories/subjects/"
        rate_limiter = get_rate_limiter()
        await rate_limiter.wait_async()
        logger.info(f"Fetching subjects list from {category_url}...")
        html = await asyncio.to_thread(_fetch_url_sync, category_url)

    if not html:
        logger.error("Failed to fetch HTML for subjects category page.")
        return {"added": 0, "updated": 0, "total": 0, "last_synced_at": None}

    parsed_subjects = parse_subjects_from_category_html(html)
    logger.info(f"Parsed {len(parsed_subjects)} subjects from category page.")

    # Fetch existing subjects from DB
    res = await db.execute(select(Subject))
    existing_by_code: Dict[str, Subject] = {s.code.upper(): s for s in res.scalars().all()}

    now = datetime.utcnow()
    added_count = 0
    updated_count = 0

    for s_data in parsed_subjects:
        code_upper = s_data["code"].upper()
        if code_upper in existing_by_code:
            subj = existing_by_code[code_upper]
            subj.forum_url = s_data["forum_url"]
            subj.last_synced_at = now
            if subj.name == subj.code and s_data["name"] != s_data["code"]:
                subj.name = s_data["name"]
            updated_count += 1
        else:
            new_subj = Subject(
                code=code_upper,
                name=s_data["name"],
                forum_url=s_data["forum_url"],
                exam_count=0,
                last_synced_at=now,
            )
            db.add(new_subj)
            existing_by_code[code_upper] = new_subj
            added_count += 1

    await db.commit()
    logger.info(f"Subject sync complete: {added_count} added, {updated_count} updated.")

    return {
        "added": added_count,
        "updated": updated_count,
        "total": len(existing_by_code),
        "last_synced_at": now.isoformat(),
    }


async def lookup_subject_by_code(
    db: AsyncSession,
    code: str,
    html_content: Optional[str] = None,
) -> Optional[Subject]:
    """
    Look up a subject by code. If not in DB, probe https://fuoverflow.com/forums/{code}/.
    If valid forum exists, automatically add to DB and return it.
    """
    clean_code = code.strip().upper()
    if not clean_code or not re.match(r"^[A-Za-z0-9_]{2,15}$", clean_code):
        return None

    # Check DB first
    res = await db.execute(select(Subject).where(Subject.code == clean_code))
    existing = res.scalar_one_or_none()
    if existing:
        return existing

    # Probe online forum
    forum_url = f"https://fuoverflow.com/forums/{clean_code}/"
    if html_content is None:
        rate_limiter = get_rate_limiter()
        await rate_limiter.wait_async()
        logger.info(f"Probing subject forum {forum_url}...")
        html_content = await asyncio.to_thread(_fetch_url_sync, forum_url)

    if not html_content:
        return None

    soup = BeautifulSoup(html_content, "html.parser")

    # Check error block or not found
    error_el = soup.select_one(".blockMessage--error, .p-title--error")
    if error_el or "The requested forum could not be found" in html_content:
        return None

    # Parse title / H1
    h1_el = soup.select_one(".p-title-value")
    raw_name = h1_el.get_text(strip=True) if h1_el else ""
    if not raw_name:
        title_el = soup.select_one("title")
        raw_name = title_el.get_text(strip=True).split("|")[0].strip() if title_el else clean_code

    name = raw_name
    if " - " in raw_name:
        parts = raw_name.split(" - ", 1)
        if parts[0].strip().upper() == clean_code:
            name = parts[1].strip()

    if name.upper() == clean_code and clean_code in KNOWN_NAMES_MAP:
        name = KNOWN_NAMES_MAP[clean_code]

    now = datetime.utcnow()
    new_subj = Subject(
        code=clean_code,
        name=name,
        forum_url=forum_url,
        exam_count=0,
        last_synced_at=now,
    )
    db.add(new_subj)
    await db.commit()
    await db.refresh(new_subj)

    logger.info(f"Subject '{clean_code}' discovered and added to DB: {name}")
    return new_subj


async def get_or_fetch_subjects(db: AsyncSession) -> List[Subject]:
    """Retrieve subjects from database; if empty, seed with known popular subjects."""
    stmt = select(Subject).order_by(Subject.code)
    result = await db.execute(stmt)
    subjects = list(result.scalars().all())

    if subjects:
        return subjects

    logger.info("Subject table empty. Populating with known subjects...")
    now = datetime.utcnow()
    for s_info in KNOWN_POPULAR_SUBJECTS:
        subject = Subject(
            code=s_info["code"],
            name=s_info["name"],
            forum_url=s_info["url"],
            exam_count=0,
            last_synced_at=now,
        )
        db.add(subject)

    await db.commit()
    result = await db.execute(select(Subject).order_by(Subject.code))
    return list(result.scalars().all())
