"""
backend/app/modules/crawler/fuexam_subjects.py
Quản lý và làm mới danh mục môn học của nền tảng fuexam.me.

Không gắn cứng danh sách môn trong code:
- Khởi tạo từ tệp data/subjects_fuexam.json (sao chép từ dữ liệu khảo sát 292 môn ban đầu).
- Cung cấp hàm refresh_fuexam_subjects() để quét động toàn bộ các node kỳ học trên fuexam.me,
  tôn trọng độ trễ 1,6 giây giữa các request, phát hiện môn mới/đổi tên/di chuyển node.
"""

from datetime import datetime
import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
BOOTSTRAP_FILE = DATA_DIR / "recon_tmp" / "subjects_fuexam.json"
ACTIVE_SUBJECTS_FILE = DATA_DIR / "subjects_fuexam.json"

DEFAULT_DELAY = 1.6
BASE_URL = "https://fuexam.me"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def ensure_bootstrap_file_exists() -> Path:
    """Đảm bảo data/subjects_fuexam.json tồn tại từ nguồn khởi tạo."""
    if not ACTIVE_SUBJECTS_FILE.exists():
        if BOOTSTRAP_FILE.exists():
            ACTIVE_SUBJECTS_FILE.parent.mkdir(parents=True, exist_ok=True)
            ACTIVE_SUBJECTS_FILE.write_text(
                BOOTSTRAP_FILE.read_text(encoding="utf-8"), encoding="utf-8"
            )
        else:
            ACTIVE_SUBJECTS_FILE.write_text("[]", encoding="utf-8")
    return ACTIVE_SUBJECTS_FILE


def load_subject_map(file_path: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """Đọc danh sách môn thành dictionary ánh xạ theo mã môn (code upper-case)."""
    target = file_path or ACTIVE_SUBJECTS_FILE
    if not target.exists():
        target = ensure_bootstrap_file_exists()

    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return {item["code"].strip().upper(): item for item in data if "code" in item}
        elif isinstance(data, dict):
            return {k.strip().upper(): v for k, v in data.items()}
    except Exception as e:
        logger.warning(f"Lỗi đọc tệp danh sách môn {target}: {e}")
    return {}


def discover_term_nodes(session: requests.Session) -> List[Dict[str, Any]]:
    """
    Quét trang chủ https://fuexam.me/ để tìm danh sách các danh mục kỳ học.
    Bao gồm: 'Tổng hợp - Chưa rõ kỳ' và 'Kỳ 0' .. 'Kỳ 9'.
    """
    from backend.app.modules.crawler.fuexam_crawler import FuexamHttpClient
    headers = {"User-Agent": USER_AGENT}
    http = FuexamHttpClient()
    resp = http.get(session, BASE_URL, headers=headers, expect_html=True)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    term_nodes: List[Dict[str, Any]] = []

    for node in soup.select(".node--category, .node--forum"):
        title_el = node.select_one(".node-title a")
        if not title_el:
            continue
        title = title_el.text.strip()
        href = title_el.get("href", "")

        # Nhận diện các node kỳ học: Kỳ 0..9 hoặc Tổng hợp
        if re.search(r"(kỳ\s*\d+|tổng\s*hợp)", title, re.IGNORECASE):
            full_url = urljoin(BASE_URL, href)
            m_id = re.search(r"\.(\d+)/?$", href)
            node_id = int(m_id.group(1)) if m_id else None
            term_nodes.append({
                "term_group": title,
                "url": full_url,
                "node_id": node_id,
            })

    return term_nodes


def parse_subjects_from_term_page(html: str, term_group: str) -> List[Dict[str, Any]]:
    """Phân tích các forum môn học bên trong trang kỳ học."""
    soup = BeautifulSoup(html, "html.parser")
    subjects: List[Dict[str, Any]] = []

    for node in soup.select(".node--forum"):
        title_el = node.select_one(".node-title a")
        if not title_el:
            continue

        raw_name = title_el.text.strip()
        href = title_el.get("href", "")
        full_url = urljoin(BASE_URL, href)

        m_id = re.search(r"\.(\d+)/?$", href)
        node_id = int(m_id.group(1)) if m_id else None

        # Trích xuất mã môn (ví dụ DTA301 từ DTA301 hoặc PRM393 từ PRM393 - Lập trình di động)
        m_code = re.match(r"^([A-Za-z0-9_\-]+)", raw_name)
        code = m_code.group(1).upper() if m_code else raw_name.upper()

        subjects.append({
            "code": code,
            "name": raw_name,
            "forum_url": full_url,
            "node_id": node_id,
            "term_group": term_group,
        })

    return subjects


def scan_all_term_nodes(
    delay_seconds: float = DEFAULT_DELAY,
    session: Optional[requests.Session] = None,
) -> List[Dict[str, Any]]:
    """
    Quét toàn bộ các node kỳ học với độ trễ tối thiểu delay_seconds (mặc định 1.6s).
    Trả về danh sách đối tượng môn học đầy đủ.
    """
    s = session or requests.Session()
    headers = {"User-Agent": USER_AGENT}

    # 1. Khám phá các danh mục kỳ học từ trang chủ
    term_nodes = discover_term_nodes(s)
    if not term_nodes:
        logger.warning("Không tìm thấy node kỳ học nào trên trang chủ fuexam.me")
        return []

    all_subjects: List[Dict[str, Any]] = []
    seen_codes = set()

    from backend.app.modules.crawler.fuexam_crawler import FuexamHttpClient
    http = FuexamHttpClient(min_delay_seconds=delay_seconds)

    for term in term_nodes:
        term_name = term["term_group"]
        term_url = term["url"]
        logger.info(f"Đang quét kỳ học: {term_name} ({term_url})")

        try:
            resp = http.get(s, term_url, headers=headers, expect_html=True)
            sub_list = parse_subjects_from_term_page(resp.text, term_group=term_name)

            # Kiểm tra phân trang nếu có
            soup = BeautifulSoup(resp.text, "html.parser")
            page_links = soup.select(".pageNav-page a[href*='/page-']")
            next_pages = set()
            for pl in page_links:
                p_href = pl.get("href")
                if p_href:
                    next_pages.add(urljoin(BASE_URL, p_href))

            for page_url in sorted(next_pages):
                p_resp = http.get(s, page_url, headers=headers, expect_html=True)
                if p_resp.status_code == 200:
                    p_subs = parse_subjects_from_term_page(p_resp.text, term_group=term_name)
                    sub_list.extend(p_subs)

            for item in sub_list:
                c = item["code"]
                if c not in seen_codes:
                    seen_codes.add(c)
                    all_subjects.append(item)

        except Exception as e:
            logger.error(f"Lỗi khi quét node kỳ học {term_name}: {e}")

    return all_subjects


def compare_and_diff_subjects(
    old_map: Dict[str, Dict[str, Any]],
    new_subjects: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """So sánh danh sách cũ và mới để phát hiện: môn mới, đổi tên, đổi URL, hoặc bị xóa."""
    new_map = {item["code"].strip().upper(): item for item in new_subjects}

    added = []
    renamed = []
    moved = []
    unchanged = []

    for code, new_item in new_map.items():
        if code not in old_map:
            added.append(new_item)
        else:
            old_item = old_map[code]
            is_renamed = old_item.get("name") != new_item.get("name")
            is_moved = (
                old_item.get("forum_url") != new_item.get("forum_url")
                or old_item.get("term_group") != new_item.get("term_group")
            )

            if is_renamed:
                renamed.append({
                    "code": code,
                    "old_name": old_item.get("name"),
                    "new_name": new_item.get("name"),
                })
            if is_moved:
                moved.append({
                    "code": code,
                    "old_url": old_item.get("forum_url"),
                    "new_url": new_item.get("forum_url"),
                    "old_term": old_item.get("term_group"),
                    "new_term": new_item.get("term_group"),
                })
            if not is_renamed and not is_moved:
                unchanged.append(code)

    removed = [
        old_map[code] for code in old_map if code not in new_map
    ]

    return {
        "timestamp": datetime.now().isoformat(),
        "total_new": len(new_subjects),
        "total_old": len(old_map),
        "added": added,
        "renamed": renamed,
        "moved": moved,
        "removed": removed,
        "unchanged_count": len(unchanged),
    }


def refresh_fuexam_subjects(
    delay_seconds: float = DEFAULT_DELAY,
    save_to_disk: bool = True,
    target_file: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Hàm làm mới danh sách môn:
    - Quét lại toàn bộ các node kỳ học trên fuexam.me.
    - So sánh với dữ liệu hiện tại để phát hiện thay đổi.
    - Lưu vào tệp JSON nếu save_to_disk=True.
    - Trả về bản báo cáo diff chi tiết.
    """
    save_path = target_file or ACTIVE_SUBJECTS_FILE
    ensure_bootstrap_file_exists()

    old_map = load_subject_map(save_path)
    new_subjects = scan_all_term_nodes(delay_seconds=delay_seconds)

    if not new_subjects:
        logger.warning("Không lấy được môn nào từ fuexam.me; giữ nguyên danh sách hiện tại.")
        return {
            "success": False,
            "error": "Quét thất bại hoặc danh sách rỗng",
            "total_old": len(old_map),
        }

    diff_report = compare_and_diff_subjects(old_map, new_subjects)

    if save_to_disk:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        # Lưu file nguyên tử (atomic write qua tệp tạm)
        temp_file = save_path.with_suffix(".tmp")
        temp_file.write_text(
            json.dumps(new_subjects, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temp_file.replace(save_path)
        logger.info(f"Đã cập nhật danh sách môn thành công vào {save_path} ({len(new_subjects)} môn).")

    return {
        "success": True,
        "diff": diff_report,
        "total_subjects": len(new_subjects),
    }


FUEXAM_TYPE_ORDER: Tuple[str, ...] = ("FE", "RE", "PE", "B5")
_SUBJECT_CODE_TOKEN_RE = re.compile(r"^[A-Z]{2,6}\d{2,4}[A-Z0-9]*$")
_NON_EXAM_TITLE_RE = re.compile(
    r"^(?:hỏi\s*đáp|tải\s*ảnh|hướng\s*dẫn|thảo\s*luận|quy\s*định|thông\s*báo)\b",
    re.IGNORECASE,
)
_NON_EXAM_PREFIXES = {"hỏi đáp", "góp ý", "thảo luận", "hướng dẫn", "thông báo", "quy định"}


def extract_fuexam_thread_subject_code(
    raw_title: str,
    known_codes: Optional[Set[str]] = None,
    tag_texts: Optional[List[str]] = None,
) -> Optional[str]:
    """
    Xác định mã môn của một thread fuexam bằng khớp token đầu tiên nguyên văn
    (không phân biệt hoa thường), hoặc tag/chuyên mục tường minh nếu có.
    Tuyệt đối không dùng khớp chuỗi con hay tìm kiếm full-text.
    """
    if not raw_title or not raw_title.strip():
        return None

    cleaned = raw_title.strip()
    tokens = [t for t in re.split(r"[\s\-–—_:/|,\[\]()]+", cleaned) if t]
    if tokens:
        first_tok = tokens[0].upper()
        if known_codes is not None and first_tok in known_codes:
            return first_tok
        if _SUBJECT_CODE_TOKEN_RE.match(first_tok):
            return first_tok

    if tag_texts and not _NON_EXAM_TITLE_RE.match(cleaned):
        for tag in tag_texts:
            tag_u = tag.strip().upper()
            if not tag_u:
                continue
            if (known_codes is not None and tag_u in known_codes) or _SUBJECT_CODE_TOKEN_RE.match(tag_u):
                return tag_u

    return None


def classify_fuexam_thread_tokens(
    raw_title: str,
    prefix_text: str = "",
) -> Tuple[Optional[str], List[str], Optional[str]]:
    """
    Phân loại thread fuexam dựa trên token loại trong tiêu đề (FE, RE, PE, B5...)
    và nhãn prefix của XenForo, không dựa vào chuỗi con ngẫu nhiên.
    Trả về (exam_type, type_tags, term).
    """
    cleaned_title = (raw_title or "").strip()
    cleaned_prefix = (prefix_text or "").strip()

    if not cleaned_title:
        return None, [], None
    if cleaned_prefix.lower() in _NON_EXAM_PREFIXES or _NON_EXAM_TITLE_RE.match(cleaned_title):
        return None, [], None

    term_match = re.search(r"\b(SU|FA|SP|WI)\s*(\d{2,4})\b", cleaned_title, re.IGNORECASE)
    term = f"{term_match.group(1).upper()}{term_match.group(2)[-2:]}" if term_match else None

    raw_tokens = [t for t in re.split(r"[^A-Za-z0-9À-ỹ]+", cleaned_title) if t]
    body_tokens = [t.upper() for t in raw_tokens]
    if body_tokens and _SUBJECT_CODE_TOKEN_RE.match(body_tokens[0]):
        body_tokens = body_tokens[1:]

    found_tags: Set[str] = set()
    for tok in body_tokens:
        if tok == "PE" or re.match(r"^C\d+PE$", tok):
            found_tags.add("PE")
        elif tok == "FE" or re.match(r"^C\d+FE$", tok):
            found_tags.add("FE")
        elif tok == "RE":
            found_tags.add("RE")
        elif tok == "B5":
            found_tags.add("B5")

    if cleaned_prefix:
        prefix_tokens = [t.upper() for t in re.split(r"[^A-Za-z0-9À-ỹ]+", cleaned_prefix) if t]
        if "PE" in prefix_tokens:
            found_tags.add("PE")
        elif "FE" in prefix_tokens:
            found_tags.add("FE")

    ordered_tags = [tag for tag in FUEXAM_TYPE_ORDER if tag in found_tags]
    if "PE" in found_tags:
        exam_type = "PE"
    elif "FE" in found_tags or "RE" in found_tags:
        exam_type = "FE"
    else:
        exam_type = None

    return exam_type, ordered_tags, term


def parse_fuexam_forum_threads(
    html: str,
    expected_subject_code: str,
    known_codes: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Phân tích HTML danh sách thread của một môn trên fuexam.me:
    - Gán môn bằng token đầu tiên khớp chính xác (hoặc tag tường minh).
    - Bỏ và ghi log cảnh báo nếu không xác định được môn hoặc sai môn hoặc không rõ loại đề.
    - Không khớp chuỗi con, không thêm dữ liệu giả.
    """
    if not html:
        return []

    target_code = expected_subject_code.strip().upper()
    soup = BeautifulSoup(html, "html.parser")
    parsed: List[Dict[str, Any]] = []

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
        full_url = urljoin(BASE_URL, clean_href) if clean_href.startswith("/") else clean_href

        m_id = re.search(r"\.(\d+)/?$", clean_href)
        if not m_id:
            continue
        tid = int(m_id.group(1))

        tag_texts = [el.get_text(strip=True) for el in item.select(".tagItem")]
        assigned_subject = extract_fuexam_thread_subject_code(
            raw_title,
            known_codes=known_codes,
            tag_texts=tag_texts,
        )
        if not assigned_subject:
            logger.warning(
                "[fuexam] Bỏ qua thread #%s (%r): không xác định được mã môn học.",
                tid,
                raw_title,
            )
            continue

        if assigned_subject != target_code:
            logger.warning(
                "[fuexam] Bỏ qua thread #%s (%r): thuộc môn %s, không phải %s.",
                tid,
                raw_title,
                assigned_subject,
                target_code,
            )
            continue

        exam_type, type_tags, term = classify_fuexam_thread_tokens(raw_title, prefix_text)
        if not exam_type:
            logger.warning(
                "[fuexam] Bỏ qua thread #%s (%r): không xác định được loại đề (FE/RE/PE).",
                tid,
                raw_title,
            )
            continue

        date_el = item.select_one("time[datetime]")
        post_date = None
        if date_el and date_el.get("datetime"):
            try:
                post_date = datetime.fromisoformat(date_el["datetime"])
            except Exception:
                post_date = None

        is_valid_exam = exam_type != "PE"
        warning = None
        if exam_type == "PE":
            warning = "PE chưa hỗ trợ trên fuexam"
        elif "B5" in type_tags:
            warning = "Mã đề B5: kèm dải đáp án gốc"
        elif "RE" in type_tags:
            warning = "Đề thi lại (RE): đáp án từ bình luận"

        parsed.append({
            "id": tid,
            "title": raw_title,
            "url": full_url,
            "assigned_subject": assigned_subject,
            "exam_type": exam_type,
            "type_tags": type_tags,
            "term": term,
            "post_date": post_date,
            "is_valid_exam": is_valid_exam,
            "warning": warning,
        })

    return parsed
