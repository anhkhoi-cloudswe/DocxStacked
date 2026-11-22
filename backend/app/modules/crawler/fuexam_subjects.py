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
from typing import Any, Dict, List, Optional, Tuple
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
    headers = {"User-Agent": USER_AGENT}
    resp = session.get(BASE_URL, headers=headers, timeout=20)
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

    for term in term_nodes:
        term_name = term["term_group"]
        term_url = term["url"]
        logger.info(f"Đang quét kỳ học: {term_name} ({term_url})")

        # Tôn trọng độ trễ 1.6 giây
        time.sleep(delay_seconds)

        try:
            resp = s.get(term_url, headers=headers, timeout=20)
            resp.raise_for_status()
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
                time.sleep(delay_seconds)
                p_resp = s.get(page_url, headers=headers, timeout=20)
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
