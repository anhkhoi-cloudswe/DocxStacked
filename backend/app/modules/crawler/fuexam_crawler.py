"""
backend/app/modules/crawler/fuexam_crawler.py
Module cào dữ liệu, quản lý phiên và bộ nhớ đệm (Cache) cho nền tảng fuexam.me.

Tuân thủ nghiêm ngặt các quy tắc:
1. Luôn sử dụng phiên đăng nhập hợp lệ (từ data/auth/fuexam_storage_state.json).
   Nếu phiên không hợp lệ hoặc hết hạn -> Dừng ngay lập tức với trạng thái 'cần đăng nhập'.
2. Cache ảnh và bình luận theo media_id kèm thời điểm lấy (fetched_at).
   Tái sử dụng cache để soạn thảo lại mà không tải lại mạng.
3. Hỗ trợ tùy chọn force_refresh=True để làm mới bắt buộc.
4. Tôn trọng độ trễ an toàn tối thiểu 1.6 giây giữa các request mạng.
"""

from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import numpy as np
from PIL import Image
import requests

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
AUTH_FILE = DATA_DIR / "auth" / "fuexam_storage_state.json"
CACHE_DIR = DATA_DIR / "cache" / "fuexam"
RAW_DIR = DATA_DIR / "raw" / "fuexam"

BASE_URL = "https://fuexam.me"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
DEFAULT_DELAY = 1.6


class AuthenticationRequiredError(Exception):
    """Ngoại lệ khi chưa có phiên đăng nhập hoặc phiên đã hết hạn."""
    pass


def get_authenticated_session() -> requests.Session:
    """Khởi tạo requests.Session mang cookie phiên từ storage_state."""
    if not AUTH_FILE.exists():
        raise AuthenticationRequiredError(
            "Cần đăng nhập fuexam.me: Không tìm thấy data/auth/fuexam_storage_state.json. "
            "Vui lòng mở Dashboard để đăng nhập hoặc chạy cửa sổ Chromium: python scripts/fuexam_login.py"
        )

    try:
        state = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        raise AuthenticationRequiredError(f"Tệp phiên bị lỗi không thể đọc: {e}")

    cookies = state.get("cookies", [])
    has_auth_cookie = any(
        c.get("name") in ("xf_user", "xf_session", "xf_user_session") and c.get("value")
        for c in cookies
    )
    if not has_auth_cookie:
        raise AuthenticationRequiredError(
            "Cần đăng nhập fuexam.me: Không có cookie xác thực trong tệp phiên."
        )

    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "vi,en-US;q=0.9,en;q=0.8",
    })

    for c in cookies:
        session.cookies.set(
            name=c["name"],
            value=c["value"],
            domain=c.get("domain", "").lstrip("."),
            path=c.get("path", "/"),
        )

    return session


def check_session_validity(session: requests.Session) -> bool:
    """Kiểm tra xem phiên có còn hợp lệ không trước khi bắt đầu cào (dùng public thread, không gọi /account/)."""
    probe_url = "https://fuexam.me/threads/prm393-su26-fe-re.941/"
    try:
        resp = session.get(probe_url, allow_redirects=True, timeout=15)
        if resp.status_code == 200 and "/login" not in resp.url and 'data-logged-in="true"' in resp.text:
            return True
        return False
    except Exception:
        return False


def get_media_cache_dir(media_id: int) -> Path:
    """Thư mục lưu cache riêng cho từng media_id."""
    m_dir = CACHE_DIR / f"media_{media_id}"
    m_dir.mkdir(parents=True, exist_ok=True)
    return m_dir


def extract_thread_questions(
    thread_url: str,
    session: requests.Session,
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Quét thread bài viết để trích xuất danh sách tất cả các ảnh câu hỏi đính kèm.
    Trả về (tiêu đề thread, danh sách các mục câu hỏi).
    """
    resp = session.get(thread_url, timeout=25)
    if resp.status_code == 403 or "/login" in resp.url or 'data-logged-in="false"' in resp.text:
        raise AuthenticationRequiredError("Phiên đăng nhập đã hết hạn khi tải thread.")

    soup = BeautifulSoup(resp.text, "html.parser")
    thread_title = soup.title.string.strip() if soup.title else "Đề Thi fuexam.me"
    # Dọn bớt hậu tố title
    thread_title = re.sub(r"\s*\|\s*FuExam.*$", "", thread_title).strip()

    questions: List[Dict[str, Any]] = []
    previews = soup.select("section.message-attachments a.file-preview")

    for idx, prev in enumerate(previews, 1):
        href = prev.get("href", "")
        sb_href = prev.get("data-lb-sidebar-href", "")

        # Trích xuất attachment_id từ href (ví dụ /attachments/...-webp.68981/)
        m_att = re.search(r"\.(\d+)/?$", href)
        attachment_id = int(m_att.group(1)) if m_att else None

        # Trích xuất media_id từ data-lb-sidebar-href (ví dụ /media/...-webp.34522/?lightbox=1)
        m_med = re.search(r"/media/(?:[^/?]+\.)?(\d+)/?", sb_href)
        media_id = int(m_med.group(1)) if m_med else (attachment_id or idx)

        # Trích xuất slug
        m_slug = re.search(r"/media/([^/?]+)\.\d+/?", sb_href)
        slug = m_slug.group(1) if m_slug else f"q_{idx}"

        alt = prev.find("img").get("alt", f"Câu {idx}") if prev.find("img") else f"Câu {idx}"

        questions.append({
            "index": idx,
            "title": alt,
            "slug": slug,
            "media_id": media_id,
            "attachment_id": attachment_id,
            "attachment_url": urljoin(BASE_URL, href),
            "media_url": f"https://fuexam.me/media/{slug}.{media_id}/",
        })

    return thread_title, questions


def fetch_and_cache_media_image(
    media_id: int,
    attachment_url: str,
    slug: str,
    session: requests.Session,
    force_refresh: bool = False,
    delay_seconds: float = DEFAULT_DELAY,
) -> Tuple[Path, bool]:
    """
    Tải và lưu cache ảnh đề thi theo media_id.
    Nếu cache đã có và force_refresh=False: Đọc từ cache ngay lập tức (không gọi mạng).
    Trả về (đường dẫn file ảnh, is_cached).
    """
    m_dir = get_media_cache_dir(media_id)
    raw_image_path = m_dir / f"{slug}.webp"
    meta_path = m_dir / "image_meta.json"

    if not force_refresh and raw_image_path.exists() and meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("file_size", 0) > 0:
                logger.debug(f"[Cache Hit] Sử dụng ảnh từ cache: {raw_image_path}")
                return raw_image_path, True
        except Exception:
            pass

    # Gọi mạng với phiên đăng nhập
    time.sleep(delay_seconds)
    resp = session.get(attachment_url, allow_redirects=True, timeout=25)

    if resp.status_code != 200 or len(resp.content) < 100:
        # Nếu đường attachments bị chặn, thử đường /media/.../full kèm cookie phiên
        media_full_url = f"https://fuexam.me/media/{slug}.{media_id}/full"
        time.sleep(delay_seconds)
        resp = session.get(media_full_url, allow_redirects=True, timeout=25)
        if resp.status_code != 200 or len(resp.content) < 100:
            raise RuntimeError(f"Không thể tải ảnh media {media_id} (HTTP {resp.status_code})")

    # Lưu ảnh vào cache
    raw_image_path.write_bytes(resp.content)
    sha256_hash = hashlib.sha256(resp.content).hexdigest()

    meta_data = {
        "media_id": media_id,
        "slug": slug,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source_url": attachment_url,
        "sha256": sha256_hash,
        "file_size": len(resp.content),
    }
    meta_path.write_text(json.dumps(meta_data, indent=2, ensure_ascii=False), encoding="utf-8")

    return raw_image_path, False


def fetch_and_cache_media_comments(
    media_id: int,
    slug: str,
    session: requests.Session,
    force_refresh: bool = False,
    delay_seconds: float = DEFAULT_DELAY,
) -> Tuple[List[Dict[str, Any]], bool]:
    """
    Tải và lưu cache bình luận của câu hỏi theo media_id.
    Nếu cache đã có và force_refresh=False: Tái sử dụng cache ngay lập tức.
    Trả về (danh sách bình luận, is_cached).
    """
    m_dir = get_media_cache_dir(media_id)
    comments_file = m_dir / "comments.json"

    if not force_refresh and comments_file.exists():
        try:
            cached_payload = json.loads(comments_file.read_text(encoding="utf-8"))
            logger.debug(f"[Cache Hit] Đọc {len(cached_payload.get('comments', []))} bình luận từ cache media {media_id}")
            return cached_payload.get("comments", []), True
        except Exception:
            pass

    # Gọi mạng với phiên đăng nhập
    media_url = f"https://fuexam.me/media/{slug}.{media_id}/"
    time.sleep(delay_seconds)
    resp = session.get(media_url, timeout=20)

    if resp.status_code != 200:
        logger.warning(f"Không thể tải trang media {media_url} (HTTP {resp.status_code})")
        return [], False

    soup = BeautifulSoup(resp.text, "html.parser")
    comment_articles = soup.select(".message--comment")
    parsed_comments: List[Dict[str, Any]] = []

    for c in comment_articles:
        c_id = c.get("data-content") or c.get("id") or ""
        m_id_match = re.search(r"\d+", c_id)
        numeric_id = int(m_id_match.group(0)) if m_id_match else None

        author_el = c.select_one(".username")
        author_name = author_el.text.strip() if author_el else "Thành viên"
        author_hash = hashlib.sha256(author_name.encode("utf-8")).hexdigest()[:12]

        body_el = c.select_one(".bbWrapper")
        # Bóc tách nội dung quote để tránh nhận nhầm đáp án của quote
        quote_el = body_el.select_one("blockquote") if body_el else None
        quoted_text = quote_el.text.strip() if quote_el else ""
        if quote_el:
            quote_el.decompose()

        clean_text = body_el.text.strip() if body_el else ""

        # Số reaction
        rx_bar = c.select_one(".reactionsBar")
        rx_count = 0
        if rx_bar:
            # Ví dụ: 'Bạn và 3 người khác' hoặc icon
            rx_links = rx_bar.select("a")
            rx_count = max(1, len(rx_links))

        time_el = c.select_one("time[datetime]")
        c_time = time_el.get("datetime") if time_el else ""

        parsed_comments.append({
            "comment_id": numeric_id,
            "author_name": author_name,
            "author_hash": author_hash,
            "raw_text": clean_text,
            "quoted_text": quoted_text,
            "reactions": rx_count,
            "created_at": c_time,
        })

    payload = {
        "media_id": media_id,
        "slug": slug,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "total_comments": len(parsed_comments),
        "comments": parsed_comments,
    }
    comments_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    return parsed_comments, False


from dataclasses import dataclass, field


@dataclass
class SubExam:
    exam_code: Optional[str]  # Ví dụ "Đề 1", "Mã đề 102", hoặc None
    title: str
    questions: List[Dict[str, Any]]


def extract_exam_code_chip(image_input: Union[Path, str, Image.Image]) -> np.ndarray:
    """
    Trích xuất và chuẩn hóa vùng MÃ ĐỀ trong dải banner:
    - Tìm dải banner tiêu đề ở y < 200.
    - Tìm thanh phân cách '|' hoặc khoảng trống lớn (> 20px) ngăn giữa MÃ ĐỀ và 'Question N'.
    - Lấy riêng vùng chứa MÃ ĐỀ, LOẠI BỎ vùng số câu hỏi.
    - Chuẩn hóa về (128, 32) grayscale float32.
    """
    if isinstance(image_input, (str, Path)):
        p = Path(image_input)
        if not p.exists():
            return np.zeros((32, 128), dtype=np.float32)
        try:
            im = Image.open(p).convert("RGB")
        except Exception:
            return np.zeros((32, 128), dtype=np.float32)
    elif isinstance(image_input, Image.Image):
        im = image_input.convert("RGB")
    else:
        return np.zeros((32, 128), dtype=np.float32)

    arr = np.array(im)
    dark = (arr[:200, :] < 180).all(axis=2)
    green = (
        (arr[:200, ..., 1].astype(int) - arr[:200, ..., 0].astype(int) >= 20)
        & (arr[:200, ..., 1].astype(int) - arr[:200, ..., 2].astype(int) >= 10)
    )
    content = dark | green
    rc = content.sum(axis=1)
    ys = np.where(rc > 50)[0]
    if len(ys) == 0:
        return np.zeros((32, 128), dtype=np.float32)
    y1, y2 = ys.min(), ys.max() + 1

    banner = content[y1:y2, :]
    cc = banner.sum(axis=0)
    xs = np.where(cc > 2)[0]
    if len(xs) == 0:
        return np.zeros((32, 128), dtype=np.float32)

    x_start = xs.min()
    x_end = None
    prev = xs[0]
    for x in xs[1:]:
        if x - prev >= 20:
            x_end = prev
            break
        prev = x

    if x_end is None or (x_end - x_start < 100):
        x_end = x_start + int(0.50 * (xs.max() - xs.min()))

    code_region = arr[y1:y2, x_start : x_end + 1]
    im_gray = Image.fromarray(code_region).convert("L").resize((128, 32), Image.Resampling.BILINEAR)
    return np.array(im_gray, dtype=np.float32)


def compute_exam_code_distance(feat1: np.ndarray, feat2: np.ndarray) -> float:
    """Khoảng cách tương đồng chuẩn hóa L1 giữa 2 vùng mã đề (0.0 = giống hệt, 1.0 = khác hoàn toàn)."""
    return float(np.mean(np.abs(feat1 - feat2))) / 255.0


def hash_banner_exam_code(image_input: Union[Path, str, Image.Image]) -> str:
    """
    Tạo perceptual hash bền vững cho vùng mã đề:
    Dùng average hash (16x8) trên vùng mã đề đã chuẩn hóa để phân nhóm chống nhiễu.
    """
    feat = extract_exam_code_chip(image_input)
    m = feat.mean()
    bits = (feat[::4, ::8] > m).flatten()
    return "".join("1" if b else "0" for b in bits)


def mock_ai_read_exam_code_from_banner(banner_im: Image.Image, default_code: str = "Mã đề 1") -> str:
    """
    Hàm đọc mã đề từ dải banner bằng AI Vision (chỉ gọi 1 lần cho mỗi nhóm ảnh).
    Trong môi trường kiểm thử / offline, đọc qua OCR đơn giản hoặc trả về mã đề chuẩn.
    """
    return default_code


@dataclass
class ThreadFilterResult:
    is_valid: bool
    exam_type: Optional[str] = None  # "FE" hoặc "PE"
    rejection_reason: Optional[str] = None
    sub_exams: List[SubExam] = field(default_factory=list)


def filter_and_classify_thread(
    thread_title: str,
    thread_url: str,
    questions: List[Dict[str, Any]],
    raw_html: Optional[str] = None,
    ai_exam_code_reader: Optional[Any] = None,
) -> ThreadFilterResult:
    """
    Bộ lọc 3 lớp cho thread trên fuexam.me:
    Lớp 1: Kiểm tra URL và Cây diễn đàn thực tế (TÀI LIỆU CÁC MÔN HỌC / Kỳ N / môn).
           Từ chối thread hỏi đáp (ví dụ /threads/tai-anh.857/), ngoài cây môn học.
    Lớp 2: Kiểm tra loại đề:
           - Nếu là PE (Practical Exam) -> Từ chối với lý do: "Chưa hỗ trợ PE trên fuexam"
           - Nếu là thread hỏi đáp / thảo luận -> Từ chối
    Lớp 3: Kiểm tra số lượng ảnh: Yêu cầu tối thiểu 10 ảnh câu hỏi (đề thi thật).
    Tách nhiều mã đề: Nhóm ảnh theo hash dải banner phần mã đề (không dùng regex trên tiêu đề thread).
                      Nếu có >= 2 nhóm mã đề -> gọi AI nhìn dải banner 1 lần mỗi nhóm để tách file.
    """
    # Lớp 1: URL & Cây diễn đàn thực tế
    if not thread_url or not ("/threads/" in thread_url or "/forums/" in thread_url):
        return ThreadFilterResult(
            is_valid=False,
            rejection_reason="URL không đúng định dạng thread của fuexam.me",
        )

    t_clean = thread_title.strip()

    # Kiểm tra cây diễn đàn thực tế từ breadcrumbs trong HTML
    if raw_html:
        soup = BeautifulSoup(raw_html, "html.parser")
        breadcrumbs = [a.get_text(strip=True) for a in soup.select(".p-breadcrumbs a")]
        bc_text = " / ".join(breadcrumbs)

        # Cây diễn đàn chuẩn: phải chứa 'TÀI LIỆU CÁC MÔN HỌC' hoặc thuộc node môn học
        if breadcrumbs and "TÀI LIỆU CÁC MÔN HỌC" not in bc_text and not re.search(r"Kỳ\s*\d+", bc_text, re.IGNORECASE):
            return ThreadFilterResult(
                is_valid=False,
                rejection_reason="Thread không thuộc cây môn học (TÀI LIỆU CÁC MÔN HỌC / Kỳ N / môn)",
            )

    # Kiểm tra thread hỏi đáp / hướng dẫn cụ thể (ví dụ /threads/tai-anh.857/)
    if re.search(r"/threads/(?:tai-anh|hoi-dap|gop-y|thao-luan)\b", thread_url, re.IGNORECASE) or \
       re.search(r"^(?:Hỏi\s*đáp|Tải\s*ảnh|Hướng\s*dẫn|Thảo\s*luận)\b", t_clean, re.IGNORECASE):
        return ThreadFilterResult(
            is_valid=False,
            rejection_reason="Thread không phải là bài đăng đề thi (tài liệu/thảo luận/hỏi đáp)",
        )

    # Lớp 2: Kiểm tra loại đề (PE vs FE)
    pe_pattern = r"(?:\bPE\b|Đề\s*Thi\s*PE|Practical\s*Exam)"
    if re.search(pe_pattern, t_clean, re.IGNORECASE):
        return ThreadFilterResult(
            is_valid=False,
            exam_type="PE",
            rejection_reason="Chưa hỗ trợ PE trên fuexam",
        )

    # Lớp 3: Kiểm tra số lượng ảnh câu hỏi (yêu cầu tối thiểu 10 ảnh)
    if not questions or len(questions) < 10:
        count = len(questions) if questions else 0
        return ThreadFilterResult(
            is_valid=False,
            rejection_reason=f"Thread có ít hơn 10 ảnh câu hỏi (chỉ có {count} ảnh, yêu cầu tối thiểu 10)",
        )

    # TÁCH MÃ ĐỀ: Nhóm ảnh theo khoảng cách tương đồng vùng mã đề (bền với nhiễu nén, loại trừ số câu)
    groups: List[Dict[str, Any]] = []
    DIST_THRESHOLD = 0.15

    for q in questions:
        img_p = q.get("local_image_path") or q.get("image_path")
        if img_p and Path(img_p).exists():
            feat = extract_exam_code_chip(img_p)
            matched = False
            for grp in groups:
                if grp.get("feat") is not None and compute_exam_code_distance(feat, grp["feat"]) <= DIST_THRESHOLD:
                    grp["questions"].append(q)
                    matched = True
                    break
            if not matched:
                groups.append({
                    "feat": feat,
                    "sample_img": img_p,
                    "questions": [q],
                })
        elif "banner_hash" in q:
            # Tương thích ngược với fixture/test nhân tạo
            b_hash = q["banner_hash"]
            matched = False
            for grp in groups:
                if grp.get("hash") == b_hash:
                    grp["questions"].append(q)
                    matched = True
                    break
            if not matched:
                groups.append({
                    "hash": b_hash,
                    "sample_img": q.get("sample_image"),
                    "questions": [q],
                })
        else:
            if not groups:
                groups.append({"sample_img": None, "questions": [q]})
            else:
                groups[0]["questions"].append(q)

    # Nếu chỉ có 1 nhóm mã đề -> Giữ tên nguyên như FUOverflow
    if len(groups) <= 1:
        return ThreadFilterResult(
            is_valid=True,
            exam_type="FE",
            sub_exams=[SubExam(exam_code=None, title=t_clean, questions=questions)],
        )

    # Nếu có từ 2 nhóm mã đề trở lên -> Tách thành nhiều SubExam
    ai_reader = ai_exam_code_reader or mock_ai_read_exam_code_from_banner
    sub_exams = []
    for idx_g, grp in enumerate(groups, 1):
        sample_img = grp.get("sample_img")
        code_str = f"Mã đề {idx_g:02d}"
        if sample_img:
            try:
                code_str = ai_reader(sample_img, default_code=f"Mã đề {idx_g:02d}")
            except Exception:
                code_str = f"Mã đề {idx_g:02d}"

        sub_title = f"{t_clean} - {code_str}"
        sub_exams.append(SubExam(exam_code=code_str, title=sub_title, questions=grp["questions"]))

    return ThreadFilterResult(
        is_valid=True,
        exam_type="FE",
        sub_exams=sub_exams,
    )


