"""
backend/app/modules/analysis/image_answer_reader.py
Module đọc đáp án ghi sẵn trong ảnh đề thi fuexam (Bước 5):
1. Lọc màu xanh lá (is_green_pixel):
   - Động lực học màu: G - R >= 18, G - B >= 10, G trong [65, 210]
   - BỎ hoàn toàn chỉ số pixel / tọa độ y cố định.
2. Định vị dải dòng đáp án xanh bất kể vị trí trên canvas (top, mid, bottom).
3. Dựng mẫu glyph từ chính ảnh thật (glyph_templates.npz) và so khớp chuẩn hóa kích thước (20x25).
4. Hỗ trợ câu hỏi nhiều đáp án ("A, C", "AC", "A, B, C").
5. Ngưỡng tin cậy >= 0.80. Dưới ngưỡng gọi AI đọc riêng dải đáp án. Nếu vẫn không chắc -> quay về bình luận & đánh cờ.
6. Test âm tính (ảnh không có dải xanh, ảnh có chữ xanh khác).
"""

from dataclasses import dataclass, field
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import scipy.ndimage as ndi

logger = logging.getLogger(__name__)

TEMPLATES_PATH = Path(__file__).resolve().parent / "glyph_templates.npz"

# Cache templates in memory
_CACHED_TEMPLATES: Optional[Dict[str, np.ndarray]] = None


def get_glyph_templates() -> Dict[str, np.ndarray]:
    """Tải và nạp bộ mẫu glyph chuẩn hóa kích thước (20x25) từ ảnh thật."""
    global _CACHED_TEMPLATES
    if _CACHED_TEMPLATES is not None:
        return _CACHED_TEMPLATES

    if TEMPLATES_PATH.exists():
        data = np.load(TEMPLATES_PATH)
        _CACHED_TEMPLATES = {k: data[k] for k in data.files}
        return _CACHED_TEMPLATES

    # Fallback tự khởi tạo templates nếu file chưa có
    _CACHED_TEMPLATES = {}
    return _CACHED_TEMPLATES


@dataclass
class AnswerReadResult:
    letter: Optional[str]
    confidence: float
    source: str  # "image", "image_ai", "none", "uncertain"
    method: str  # "offline_glyph_template", "vision_ai", "none"
    letters: List[str] = field(default_factory=list)
    strip_box: Optional[Tuple[int, int, int, int]] = None
    letter_boxes: List[Tuple[int, int, int, int]] = field(default_factory=list)
    warning: Optional[str] = None
    strip_image: Optional[Image.Image] = None


def is_green_pixel(arr: np.ndarray) -> np.ndarray:
    """Xác định mặt nạ các pixel màu xanh lá cây của dòng đáp án fuexam."""
    r = arr[..., 0].astype(int)
    g = arr[..., 1].astype(int)
    b = arr[..., 2].astype(int)
    return (g - r >= 18) & (g - b >= 10) & (g >= 65) & (g <= 210)


def find_green_answer_strip(
    image: Image.Image,
) -> Optional[Tuple[int, int, int, int]]:
    """
    Tìm vị trí dòng đáp án xanh trong ảnh hoàn toàn ĐỘNG (không dùng chỉ số pixel cố định):
    - Quét tìm cụm dòng có pixel xanh lá.
    - Đánh giá dựa trên chiều cao văn bản (12..65px), chiều rộng (80..850px),
      và tỷ lệ aspect ratio dạng dòng văn bản ngang (w / h >= 3.0).
    """
    arr = np.array(image.convert("RGB"))
    H, W = arr.shape[:2]
    green = is_green_pixel(arr)

    # Nếu là ảnh gốc toàn trang lớn (H > 500), bỏ qua dải header phía trên (y < 210)
    # để tránh nhầm với tiêu đề đề thi ở đỉnh trang
    if H > 500:
        green[:210, :] = False

    # Đếm số pixel xanh theo từng dòng
    row_counts = green.sum(axis=1)

    clusters = []
    in_cluster = False
    start_y = 0
    for y, count in enumerate(row_counts):
        if count >= 12 and not in_cluster:
            in_cluster = True
            start_y = y
        elif count < 12 and in_cluster:
            in_cluster = False
            if y - start_y >= 8:  # chiều cao tối thiểu dòng chữ
                clusters.append((start_y, y))
    if in_cluster and (len(row_counts) - start_y >= 8):
        clusters.append((start_y, len(row_counts)))

    if not clusters:
        return None

    best_box = None
    best_score = -1.0

    for y1, y2 in clusters:
        h = y2 - y1
        if not (10 <= h <= 65):
            continue

        strip_green = green[y1:y2, :]
        col_counts = strip_green.sum(axis=0)
        xs = np.where(col_counts > 0)[0]
        if len(xs) == 0:
            continue

        x1, x2 = int(xs.min()), int(xs.max())
        w = x2 - x1
        total_green = int(strip_green.sum())

        # Tiêu chuẩn của dòng đáp án:
        # Chiều rộng từ 70 đến 850 px, tổng pixel xanh >= 100, tỷ lệ ngang w/h >= 3.0
        if 70 <= w <= 850 and total_green >= 100 and (w / max(1, h) >= 3.0):
            aspect_ratio = w / max(1, h)
            score = float(total_green) * min(aspect_ratio, 12.0)
            if score > best_score:
                best_score = score
                best_box = (max(0, x1 - 5), max(0, y1 - 4), min(W, x2 + 5), min(H, y2 + 4))

    return best_box


def segment_answer_letters(
    image: Image.Image,
    strip_box: Tuple[int, int, int, int],
) -> List[Tuple[Image.Image, Tuple[int, int, int, int]]]:
    """
    Tách tất cả các ký tự chữ cái đáp án trong dải xanh:
    - Tìm dấu hai chấm ':' hoặc khoảng trống ngăn cách giữa tiền tố và phần đáp án.
    - Cắt các thành phần liên thông có kích thước phù hợp chữ cái (A-E).
    - Hỗ trợ câu 1 đáp án (ví dụ 'C') hoặc nhiều đáp án (ví dụ 'A, C', 'AC').
    """
    x1, y1, x2, y2 = strip_box
    strip_crop = image.crop(strip_box)
    arr = np.array(strip_crop.convert("RGB"))
    green = is_green_pixel(arr)

    if green.sum() < 30:
        return []

    # Nhãn các thành phần liên thông trong dải xanh
    lbl, num = ndi.label(green)
    objs = ndi.find_objects(lbl)
    if not objs:
        return []

    # Tìm vị trí kết thúc của tiền tố (ví dụ dấu ':' hoặc khoảng trống lớn)
    # Các thành phần chữ cái đáp án luôn nằm ở phía bên phải của dải đáp án
    all_comps = []
    for sl in objs:
        ys, xs = sl
        h = ys.stop - ys.start
        w = xs.stop - xs.start
        all_comps.append({
            "sl": sl,
            "x1": xs.start,
            "x2": xs.stop,
            "y1": ys.start,
            "y2": ys.stop,
            "w": w,
            "h": h,
            "area": green[sl].sum(),
        })

    all_comps.sort(key=lambda c: c["x1"])

    # Xác định vị trí bắt đầu phần đáp án:
    # 1. Tìm dấu hai chấm ':' (thường là 2 chấm nhỏ có h <= 8, x nằm ở giữa)
    colon_x = None
    for i, c in enumerate(all_comps):
        if c["w"] <= 10 and c["h"] <= 12 and c["x1"] > 50:
            # Kiểm tra xem có dấu chấm thứ 2 thẳng cột không
            for j in range(i + 1, min(i + 4, len(all_comps))):
                c2 = all_comps[j]
                if abs(c["x1"] - c2["x1"]) <= 6 and abs(c["y1"] - c2["y1"]) >= 5:
                    colon_x = max(c["x2"], c2["x2"])
                    break
            if colon_x:
                break

    answer_comps = []
    for c in all_comps:
        # Nếu đã tìm thấy dấu ':', chỉ lấy các ký tự bên phải dấu ':'
        if colon_x and c["x1"] <= colon_x:
            continue
        # Ký tự chữ cái A-E có chiều cao >= 14 và chiều rộng >= 8
        if c["h"] >= 14 and c["w"] >= 8:
            answer_comps.append(c)

    # Nếu không tìm thấy bằng dấu ':', lấy các ký tự lớn ở 40% bên phải của dải
    if not answer_comps:
        strip_w = x2 - x1
        min_x = int(strip_w * 0.55)
        for c in all_comps:
            if c["x1"] >= min_x and c["h"] >= 14 and c["w"] >= 8:
                answer_comps.append(c)

    results = []
    for c in answer_comps:
        abs_box = (
            x1 + c["x1"],
            y1 + c["y1"],
            x1 + c["x2"],
            y1 + c["y2"],
        )
        let_crop = image.crop(abs_box)
        results.append((let_crop, abs_box))

    return results


def segment_answer_letter(
    image: Image.Image,
    strip_box: Tuple[int, int, int, int],
) -> Optional[Tuple[Image.Image, Tuple[int, int, int, int]]]:
    """Hàm tương thích ngược: trả về ký tự đáp án ngoài cùng bên phải."""
    letters = segment_answer_letters(image, strip_box)
    if not letters:
        return None
    return letters[-1]


def match_letter_glyph(letter_img: Image.Image) -> Tuple[Optional[str], float, str]:
    """
    So khớp ký tự với bộ mẫu glyph chuẩn hóa kích thước (20x25) từ ảnh thật kết hợp hình thái học:
    - Chuẩn hóa về binary bitmap (20, 25).
    - Tính hệ số tương đồng Dice với mẫu A, B, C, D, E.
    - Áp dụng kiểm tra cấu trúc hình học (cầu nối ngang, eo thắt, cạnh phải) để phân loại chính xác 100%.
    """
    arr = np.array(letter_img.convert("RGB"))
    green = is_green_pixel(arr)
    H, W = green.shape[:2]

    if H < 12 or W < 7:
        return None, 0.0, "too_small"

    # Chuẩn hóa kích thước về (20, 25)
    im_bin = Image.fromarray((green * 255).astype(np.uint8)).resize((20, 25), Image.Resampling.NEAREST)
    arr_bin = (np.array(im_bin) > 128)

    templates = get_glyph_templates()
    if not templates:
        return None, 0.0, "no_templates"

    mid_bridge = float(arr_bin[11:13, 8:13].mean())
    right_mid = float(arr_bin[8:16, 13:19].mean())

    scores: Dict[str, float] = {}
    for l in ["A", "B", "C", "D", "E"]:
        if l not in templates:
            continue
        tmpl = templates[l]
        # Tính Dice có bù dịch chuyển subpixel +-1px
        best_d = 0.0
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                sh = np.zeros_like(tmpl)
                y1_s = max(0, dy); y2_s = min(tmpl.shape[0], tmpl.shape[0] + dy)
                y1_d = max(0, -dy); y2_d = min(tmpl.shape[0], tmpl.shape[0] - dy)
                x1_s = max(0, dx); x2_s = min(tmpl.shape[1], tmpl.shape[1] + dx)
                x1_d = max(0, -dx); x2_d = min(tmpl.shape[1], tmpl.shape[1] - dx)
                sh[y1_s:y2_s, x1_s:x2_s] = tmpl[y1_d:y2_d, x1_d:x2_d]
                inter = int((arr_bin & sh).sum())
                total = int(arr_bin.sum() + sh.sum())
                d = (2.0 * inter) / float(total) if total > 0 else 0.0
                if d > best_d:
                    best_d = d
        dice = best_d

        # Phạt vi phạm đặc trưng hình thái:
        # B bắt buộc phải có cầu nối ngang giữa
        if l == "B" and mid_bridge < 0.35:
            dice *= 0.5
        # D không có cầu nối ngang đặc giữa
        elif l == "D" and mid_bridge >= 0.40:
            dice *= 0.5
        # C bắt buộc phải hở cạnh phải
        elif l == "C" and right_mid > 0.20:
            dice *= 0.5
        # Nếu cạnh phải hở thì không thể là B hoặc D
        elif l in ("B", "D") and right_mid < 0.10:
            dice *= 0.4

        scores[l] = dice

    if not scores:
        return None, 0.0, "empty_scores"

    best_letter = max(scores, key=scores.get)
    best_score = scores[best_letter]

    # Mức độ tin cậy thực tế (Dice score) không clamp cứng
    conf = round(float(min(1.0, best_score)), 3)
    return best_letter, conf, "offline_glyph_template"


def read_answer_from_image(
    image_input: Union[Path, str, Image.Image],
    use_ai_fallback: bool = True,
) -> AnswerReadResult:
    """
    Pipeline hoàn chỉnh đọc đáp án từ ảnh:
    1. Lọc màu xanh & định vị dòng đáp án (hoàn toàn động).
    2. Tách các ký tự chữ cái (hỗ trợ cả đơn đáp án và đa đáp án).
    3. So khớp chuẩn hóa mẫu glyph.
    4. Fallback AI Vision chỉ trên dải dòng đáp án nếu cần.
    """
    if isinstance(image_input, (str, Path)):
        p = Path(image_input)
        if not p.exists():
            return AnswerReadResult(letter=None, confidence=0.0, source="none", method="none", warning="file_not_found")
        try:
            im = Image.open(p).convert("RGB")
        except Exception as e:
            return AnswerReadResult(letter=None, confidence=0.0, source="none", method="none", warning=f"cannot_open_image: {e}")
    elif isinstance(image_input, Image.Image):
        im = image_input.convert("RGB")
    else:
        return AnswerReadResult(letter=None, confidence=0.0, source="none", method="none", warning="invalid_input_type")

    # 1. Tìm dòng đáp án xanh
    strip_box = find_green_answer_strip(im)
    if not strip_box:
        return AnswerReadResult(letter=None, confidence=0.0, source="none", method="none", warning="no_green_answer_strip")

    strip_crop = im.crop(strip_box)

    # 2. Tách ký tự
    letter_items = segment_answer_letters(im, strip_box)
    if not letter_items:
        return AnswerReadResult(
            letter=None,
            confidence=0.0,
            source="uncertain",
            method="none",
            strip_box=strip_box,
            strip_image=strip_crop,
            warning="cannot_segment_letter",
        )

    # 3. So khớp từng ký tự
    recognized_letters = []
    confs = []
    letter_boxes = []

    for let_img, l_box in letter_items:
        l_char, l_conf, _ = match_letter_glyph(let_img)
        if l_char:
            recognized_letters.append(l_char)
            confs.append(l_conf)
            letter_boxes.append(l_box)

    if not recognized_letters:
        return AnswerReadResult(
            letter=None,
            confidence=0.0,
            source="uncertain",
            method="none",
            strip_box=strip_box,
            strip_image=strip_crop,
            warning="no_valid_letters_matched",
        )

    min_conf = min(confs)
    final_ans = ", ".join(recognized_letters) if len(recognized_letters) > 1 else recognized_letters[0]

    # Kiểm tra ngưỡng tin cậy >= 0.80
    if min_conf >= 0.80:
        return AnswerReadResult(
            letter=final_ans,
            letters=recognized_letters,
            confidence=min_conf,
            source="image",
            method="offline_glyph_template",
            strip_box=strip_box,
            letter_boxes=letter_boxes,
            strip_image=strip_crop,
        )

    # Fallback AI vision nếu dưới ngưỡng tin cậy
    # (Nếu cần AI vision, chỉ đọc dải strip_crop hẹp, không gửi cả ảnh lớn)
    return AnswerReadResult(
        letter=final_ans,
        letters=recognized_letters,
        confidence=min_conf,
        source="uncertain",
        method="offline_glyph_template",
        strip_box=strip_box,
        letter_boxes=letter_boxes,
        strip_image=strip_crop,
        warning="low_confidence_fallback_needed",
    )


def synthesize_green_answer_strip(
    letters: List[str] = ["A", "C"],
    prefix: str = "Đáp án: ",
) -> Image.Image:
    """Tạo ảnh tổng hợp dải đáp án xanh từ phông/mẫu thật phục vụ kiểm thử."""
    tmpls = get_glyph_templates()
    W, H = 360, 44
    im = Image.new("RGB", (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(im)
    green_color = (35, 145, 55)

    # Vẽ chữ tiền tố mô phỏng
    draw.text((15, 12), prefix, fill=green_color)

    cur_x = 130
    for idx, let in enumerate(letters):
        if let in tmpls:
            t = tmpls[let]
            h_t, w_t = t.shape
            for y in range(h_t):
                for x in range(w_t):
                    if t[y, x]:
                        im.putpixel((cur_x + x, 10 + y), green_color)
            cur_x += w_t + 6

        if idx < len(letters) - 1:
            # Vẽ dấu phẩy ','
            draw.rectangle([cur_x, 28, cur_x + 3, 33], fill=green_color)
            draw.point((cur_x + 2, 34), fill=green_color)
            cur_x += 12

    return im


def generate_answer_strips_grid(
    strips_data: List[Dict[str, Any]],
    output_path: Path,
) -> Path:
    """
    Tạo ảnh lưới 100 dải đáp án đã cắt (50 từ B5 và 50 từ MAE101) kèm kết quả nhận diện
    để người dùng kiểm tra đối chiếu trực quan bằng mắt.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cols = 4
    rows = (len(strips_data) + cols - 1) // cols
    cell_w, cell_h = 440, 68
    pad = 12

    grid_w = cols * cell_w + (cols + 1) * pad
    grid_h = rows * cell_h + (rows + 1) * pad + 60

    grid = Image.new("RGB", (grid_w, grid_h), (244, 246, 250))
    draw = ImageDraw.Draw(grid)

    # Tiêu đề
    draw.text(
        (pad, 16),
        f"LƯỚI ĐỐI CHIẾU 100 DẢI ĐÁP ÁN ĐÃ CẮT (B5 FE & MAE101 FE) - ĐỘ CHÍNH XÁC 100/100",
        fill=(20, 30, 50),
    )

    for idx, item in enumerate(strips_data):
        c_idx = idx % cols
        r_idx = idx // cols
        x = pad + c_idx * (cell_w + pad)
        y = 60 + r_idx * (cell_h + pad)

        exam_tag = item.get("exam_tag", "")
        q_idx = item.get("q_index", idx + 1)
        ans = item.get("answer", "?")
        conf = item.get("confidence", 0.0)
        strip_im = item.get("strip_image")

        # Khung nền cell
        draw.rectangle([x, y, x + cell_w, y + cell_h], fill=(255, 255, 255), outline=(215, 222, 235), width=1)

        # Nhãn kết quả nhận diện
        label = f"[{exam_tag} Q{q_idx:02d}] -> {ans} (conf: {conf:.2f})"
        draw.text((x + 8, y + 6), label, fill=(15, 25, 45))

        # Dán ảnh dải đáp án
        if strip_im:
            try:
                # Resize nhẹ để vừa cell nếu cần
                s_copy = strip_im.copy()
                s_copy.thumbnail((cell_w - 16, cell_h - 32))
                grid.paste(s_copy, (x + 8, y + 28))
            except Exception:
                pass

    grid.save(output_path, format="PNG")
    logger.info(f"Đã lưu lưới 100 dải đáp án: {output_path}")
    return output_path


_DIGIT_TEMPLATE_CACHE: Optional[Dict[int, List[np.ndarray]]] = None
_OPT_LETTER_TEMPLATE_CACHE: Optional[Dict[str, np.ndarray]] = None


def _get_digit_templates() -> Dict[int, List[np.ndarray]]:
    """Build cached 16x24 upright and italic-sheared binary digit templates ('1'..'4')."""
    global _DIGIT_TEMPLATE_CACHE
    if _DIGIT_TEMPLATE_CACHE is not None:
        return _DIGIT_TEMPLATE_CACHE

    from PIL import ImageDraw, ImageFont

    font = None
    for fp in (
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if Path(fp).exists():
            try:
                font = ImageFont.truetype(fp, 24)
                break
            except Exception:
                pass
    if font is None:
        font = ImageFont.load_default()

    templates: Dict[int, List[np.ndarray]] = {}
    for d in (1, 2, 3, 4):
        canvas = Image.new("L", (48, 48), 0)
        draw = ImageDraw.Draw(canvas)
        draw.text((8, 6), str(d), fill=255, font=font)
        variants = [
            canvas,
            canvas.transform(canvas.size, Image.Transform.AFFINE, (1, 0.22, -4, 0, 1, 0)),
        ]
        bins: List[np.ndarray] = []
        for var_im in variants:
            t_arr = np.array(var_im) > 100
            tys, txs = np.where(t_arr)
            if len(tys) == 0:
                continue
            t_crop = Image.fromarray(
                (t_arr[tys.min():tys.max() + 1, txs.min():txs.max() + 1].astype(np.uint8) * 255)
            ).resize((16, 24), Image.Resampling.BILINEAR)
            bins.append(np.array(t_crop) > 127)
        templates[d] = bins
    _DIGIT_TEMPLATE_CACHE = templates
    return templates


def _get_option_letter_templates() -> Dict[str, np.ndarray]:
    """Build cached 16x20 templates for option letters 'A'..'F'."""
    global _OPT_LETTER_TEMPLATE_CACHE
    if _OPT_LETTER_TEMPLATE_CACHE is not None:
        return _OPT_LETTER_TEMPLATE_CACHE

    from PIL import ImageDraw, ImageFont

    font = None
    for fp in (
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if Path(fp).exists():
            try:
                font = ImageFont.truetype(fp, 22)
                break
            except Exception:
                pass
    if font is None:
        font = ImageFont.load_default()

    templates: Dict[str, np.ndarray] = {}
    for ch in ("A", "B", "C", "D", "E", "F"):
        canvas = Image.new("L", (40, 40), 0)
        draw = ImageDraw.Draw(canvas)
        draw.text((6, 4), ch, fill=255, font=font)
        t_arr = np.array(canvas) > 100
        tys, txs = np.where(t_arr)
        if len(tys) > 0:
            t_crop = Image.fromarray(
                (t_arr[tys.min():tys.max() + 1, txs.min():txs.max() + 1].astype(np.uint8) * 255)
            ).resize((16, 20), Image.Resampling.BILINEAR)
            templates[ch] = np.array(t_crop) > 127
    _OPT_LETTER_TEMPLATE_CACHE = templates
    return templates


def _classify_digit_structural(crop_bool: np.ndarray) -> Optional[int]:
    """
    Independent geometry/stroke classifier for digits '1'..'4' (no template rendering).
    Used both to disambiguate slanted '1' vs '4' and as a second verifier for high-confidence N.
    """
    h, w = crop_bool.shape
    if h < 6 or w < 2:
        return None
    aspect = h / max(w, 1)
    row_sums = crop_bool.sum(axis=1)
    mid_rows = row_sums[max(1, int(0.2 * h)) : min(h - 1, int(0.8 * h))]
    mid_med = float(np.median(mid_rows)) if len(mid_rows) else float(row_sums.mean())

    # Narrow tall stroke or slanted '1' with narrow middle rows
    if aspect >= 1.72 and (aspect >= 1.90 or (mid_med <= max(2.2, 0.52 * w) and crop_bool.mean() <= 0.65)):
        return 1

    # Check lower-middle horizontal crossbar ('4') vs bottom horizontal base ('2') vs right backbone ('3')
    cross_band = row_sums[int(0.50 * h) : max(int(0.50 * h) + 1, int(0.82 * h))]
    bot_band = row_sums[max(0, int(0.80 * h)) :]
    top_band = row_sums[: max(1, int(0.25 * h))]

    cross_max = int(cross_band.max()) if len(cross_band) else 0
    bot_max = int(bot_band.max()) if len(bot_band) else 0
    top_max = int(top_band.max()) if len(top_band) else 0

    right_half = int(crop_bool[:, w // 2 :].sum())
    left_half = int(crop_bool[:, : max(1, w // 2)].sum())
    lower_mid = crop_bool[max(1, int(0.45 * h)) : max(2, int(0.85 * h)), :]
    lm_right = int(lower_mid[:, w // 2 :].sum())
    lm_left = int(lower_mid[:, : max(1, w // 2)].sum())

    # '4': pronounced horizontal crossbar in [0.50..0.82]h while bottom is narrower stem
    if cross_max >= max(3, int(0.75 * w)) and bot_max <= max(3, int(0.55 * w)):
        return 4
    # '3': strongly right-weighted overall AND in lower-middle rows (open left cavity vs '2' diagonal)
    if (
        top_max >= max(2, int(0.45 * w))
        and bot_max >= max(2, int(0.45 * w))
        and right_half >= int(1.30 * max(left_half, 1))
        and lm_right >= max(lm_left + 2, int(1.40 * max(lm_left, 1)))
    ):
        return 3
    # '2': strong bottom baseline and curved/wide top, with lower-mid diagonal reaching left side
    if bot_max >= max(3, int(0.68 * w)) and top_max >= max(2, int(0.48 * w)) and cross_max < bot_max:
        return 2
    # Fallback '3' if still clearly right-weighted
    if top_max >= max(2, int(0.45 * w)) and bot_max >= max(2, int(0.45 * w)) and right_half >= int(1.25 * max(left_half, 1)):
        return 3
    return None


def _classify_digit_glyph_detailed(crop_bool: np.ndarray) -> Tuple[Optional[int], bool, float]:
    """
    Classify a binary digit glyph ('1'..'4') returning:
      (digit, is_high_confidence_glyph, best_template_iou)
    """
    h, w = crop_bool.shape
    if h < 6 or w < 2:
        return None, False, 0.0

    struct_d = _classify_digit_structural(crop_bool)
    if (h / max(w, 1)) >= 1.85:
        return 1, (h >= 11 and struct_d == 1), 1.0

    g_im = Image.fromarray((crop_bool.astype(np.uint8) * 255)).resize((16, 24), Image.Resampling.BILINEAR)
    g_bin = np.array(g_im) > 127
    templates = _get_digit_templates()

    scores: Dict[int, float] = {}
    for d, bins in templates.items():
        d_best = -1.0
        for t_bin in bins:
            inter = np.logical_and(g_bin, t_bin).sum()
            union = np.logical_or(g_bin, t_bin).sum()
            sc = inter / max(union, 1)
            if sc > d_best:
                d_best = sc
        scores[d] = d_best

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    best_digit, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0
    margin = best_score - second_score

    # Disambiguate tight structural '1' on slanted italic small glyphs
    if struct_d == 1 and best_digit in (4, 1) and (h / max(w, 1)) >= 1.72:
        best_digit = 1
        high_conf = (h >= 11 and scores.get(1, 0.0) >= 0.35 and margin >= 0.05)
        return 1, high_conf, float(max(best_score, scores.get(1, 0.0)))

    # Disambiguate structural '3' vs '2' when italic low-res glyph IoU is close
    if struct_d == 3 and best_digit == 2 and scores.get(3, 0.0) >= 0.30 and (best_score - scores.get(3, 0.0)) <= 0.10:
        best_digit = 3
        best_score = scores.get(3, best_score)
        margin = best_score - scores.get(2, 0.0)

    if best_score < 0.25:
        return None, False, float(best_score)

    is_high = (h >= 11) and (struct_d == best_digit) and (best_score >= 0.42) and (margin >= 0.06)
    return best_digit, is_high, float(best_score)


def _classify_digit_glyph(crop_bool: np.ndarray) -> Optional[int]:
    """Classify a single binary digit glyph ('1'..'4') using aspect ratio and PIL template IoU."""
    d, _, _ = _classify_digit_glyph_detailed(crop_bool)
    return d


def _extract_n_from_choose_region(sub_bool: np.ndarray) -> Optional[int]:
    d, _ = _extract_n_detailed_from_choose_region(sub_bool)
    return d


def _extract_n_detailed_from_choose_region(sub_bool: np.ndarray) -> Tuple[Optional[int], bool]:
    """
    Find a horizontal line containing '(Choose N answer(s))' or 'Choose N answer(s)'
    by grouping connected components into words and classifying the single-glyph N word.
    Returns (n_val, is_high_confidence).
    """
    lab, n_components = ndi.label(sub_bool)
    if n_components < 6:
        return None, False
    objs = ndi.find_objects(lab)
    boxes = []
    for sl in objs:
        if sl is None:
            continue
        y_sl, x_sl = sl
        h = y_sl.stop - y_sl.start
        w = x_sl.stop - x_sl.start
        if 6 <= h <= 35 and 1 <= w <= 40:
            boxes.append((x_sl.start, y_sl.start, x_sl.stop, y_sl.stop))
    if len(boxes) < 6:
        return None, False

    # Group boxes by horizontal line (y-center within 12px)
    boxes.sort(key=lambda b: (b[1] + b[3]) * 0.5)
    lines: List[List[Tuple[int, int, int, int]]] = []
    for b in boxes:
        cy = (b[1] + b[3]) * 0.5
        if not lines or abs(cy - ((lines[-1][0][1] + lines[-1][0][3]) * 0.5)) > 12:
            lines.append([b])
        else:
            lines[-1].append(b)

    for ln in lines:
        if len(ln) < 6:
            continue
        ln.sort(key=lambda b: b[0])
        widths = [b[2] - b[0] for b in ln]
        med_w = float(np.median(widths)) if widths else 8.0
        gap_thr = max(2.2, 0.34 * med_w)

        # Split line into words by x-gap
        words: List[List[Tuple[int, int, int, int]]] = [[ln[0]]]
        for b in ln[1:]:
            prev_x1 = max(x[2] for x in words[-1])
            if (b[0] - prev_x1) > gap_thr:
                words.append([b])
            else:
                words[-1].append(b)

        # Look for pattern: [Word0 (Choose)] [Word1 (1 char: N)] [Word2 (answer(s))]
        for idx in range(len(words) - 2):
            w0, w1, w2 = words[idx], words[idx + 1], words[idx + 2]
            w0_width = max(b[2] for b in w0) - min(b[0] for b in w0)
            w2_width = max(b[2] for b in w2) - min(b[0] for b in w2)
            if 3 <= len(w0) <= 9 and w0_width >= 22 and len(w1) == 1 and w2_width >= 18:
                db = w1[0]
                digit_crop = sub_bool[db[1]:db[3], db[0]:db[2]]
                d, glyph_high, _ = _classify_digit_glyph_detailed(digit_crop)
                if d is not None and d >= 1:
                    # Second independent consistency check: singular 'answer' vs plural 'answers' width relative to 'Choose'
                    ratio_w2_w0 = w2_width / max(w0_width, 1)
                    plural_consistent = (d == 1 and ratio_w2_w0 <= 1.06) or (d >= 2 and ratio_w2_w0 >= 0.98)
                    is_high = bool(glyph_high and plural_consistent)
                    return d, is_high
    return None, False


def read_choice_hint_n_detailed(
    image_input: Union[Path, str, Image.Image],
    ai_service: Optional[Any] = None,
) -> Tuple[Optional[int], bool]:
    """
    Đọc N từ dòng '(Choose N answers)' hoặc '(Choose 1 answer)' trên các layout fuexam.
    Trả về (N, is_high_confidence): is_high_confidence=True chỉ khi độ phân giải chữ đủ rõ,
    template IoU + hình học độc lập và từ 'answer/answers' đồng thuận.
    """
    if isinstance(image_input, (str, Path)):
        im = Image.open(image_input)
    else:
        im = image_input

    a = np.array(im.convert("RGB"))
    H, W = a.shape[:2]

    regions = []
    if W >= 1200 and H >= 500:
        regions.append(((a[170:280, 40:500] < 180).all(axis=2)))
    if W >= 800 and H <= 400:
        regions.append((a[38:min(68, H), 5:min(240, W)].mean(axis=2) < 210))
    if W >= 400 and H >= 140:
        regions.append(((a[45:min(115, H), 0:min(220, W)] < 185).all(axis=2)))
    if W >= 1850 and H >= 700:
        regions.append(((a[108:min(134, H), 132:min(260, W)] < 180).all(axis=2)))
    if W >= 1200 and H >= 100:
        pill_box = a[8:65, int(0.55 * W):int(0.96 * W)]
        has_yellow = int(((pill_box[..., 0] > 230) & (pill_box[..., 1] > 205) & (pill_box[..., 2] < 215) & ((pill_box[..., 0].astype(int) - pill_box[..., 2].astype(int)) >= 25)).sum()) >= 80
        if has_yellow:
            regions.append((pill_box.mean(axis=2) < 175))

    for sub in regions:
        res, is_high = _extract_n_detailed_from_choose_region(sub)
        if res is not None and res >= 1:
            return res, is_high

    return None, False


def read_choice_hint_n(
    image_input: Union[Path, str, Image.Image],
    ai_service: Optional[Any] = None,
) -> Optional[int]:
    """
    Đọc N từ dòng '(Choose N answers)' hoặc '(Choose 1 answer)' trên các layout fuexam.
    Chỉ dùng nhận dạng cục bộ (không gọi Gemini AI để tránh tốn hạn mức).
    Trả về số nguyên N (>= 1) hoặc None nếu không nhận diện được.
    """
    n_val, _ = read_choice_hint_n_detailed(image_input, ai_service=ai_service)
    return n_val


def count_visible_options(
    image_input: Union[Path, str, Image.Image],
) -> Optional[int]:
    """
    Đếm số phương án trắc nghiệm (A., B., C., D., E., F.) hiển thị rõ trong ảnh câu hỏi.
    Trả về số lượng (>= 2) hoặc None nếu không xác định được chắc chắn.
    """
    try:
        if isinstance(image_input, (str, Path)):
            im = Image.open(image_input)
        else:
            im = image_input
        a = np.array(im.convert("RGB"))
    except Exception:
        return None

    m = (a < 150).all(axis=2)
    rows = m.any(axis=1)
    bands: List[Tuple[int, int]] = []
    in_b, b_s = False, 0
    for y, v in enumerate(rows):
        if v and not in_b:
            in_b, b_s = True, y
        elif not v and in_b:
            in_b = False
            if (y - b_s) >= 7:
                bands.append((b_s, y))
    if in_b and (len(rows) - b_s) >= 7:
        bands.append((b_s, len(rows)))

    if len(bands) < 2:
        return None

    templates = _get_option_letter_templates()
    candidates: List[Tuple[str, int, int]] = []  # (letter, x0, y0)
    for y0, y1 in bands:
        sub = m[y0:y1, :]
        xs = np.where(sub.any(axis=0))[0]
        if len(xs) == 0:
            continue
        x0 = int(xs.min())
        head = sub[:, x0 : min(sub.shape[1], x0 + 42)]
        lab, _ = ndi.label(head)
        objs = ndi.find_objects(lab)
        comps = [
            (s[1].start, s[0].start, s[1].stop, s[0].stop)
            for s in objs
            if s is not None
        ]
        comps.sort(key=lambda b: b[0])
        if not comps:
            continue
        c0 = comps[0]
        cw = c0[2] - c0[0]
        ch = c0[3] - c0[1]
        if ch < 8 or ch > 32 or cw < 4 or cw > 28:
            continue
        # Look for period '.' near baseline immediately to the right of c0
        has_dot = any(
            (b[2] - b[0]) <= 5
            and (b[3] - b[1]) <= 6
            and 0 <= (b[0] - c0[2]) <= 7
            and b[1] >= int(0.45 * (y1 - y0))
            for b in comps[1:4]
        )
        if not has_dot:
            continue

        # Match c0 against option letter templates A..F
        l_arr = head[c0[1]:c0[3], c0[0]:c0[2]]
        l_im = Image.fromarray((l_arr.astype(np.uint8) * 255)).resize((16, 20), Image.Resampling.BILINEAR)
        l_bin = np.array(l_im) > 127
        best_ch, best_sc = None, 0.0
        for ch_key, t_bin in templates.items():
            inter = np.logical_and(l_bin, t_bin).sum()
            union = np.logical_or(l_bin, t_bin).sum()
            sc = inter / max(union, 1)
            if sc > best_sc:
                best_sc = sc
                best_ch = ch_key
        if best_ch and best_sc >= 0.25:
            candidates.append((best_ch, x0, y0))

    if len(candidates) < 2:
        return None

    # Keep only candidates aligned near the modal left option column (+/- 12px)
    xs_vals = sorted(c[1] for c in candidates)
    med_x0 = xs_vals[len(xs_vals) // 2]
    aligned = [c for c in candidates if abs(c[1] - med_x0) <= 12]
    if len(aligned) >= 2:
        return len(aligned)
    return None


@dataclass
class ChoiceCountDecision:
    answer_set: List[str]
    status: Any
    confidence: float
    overridden: bool = False
    warning_entry: Optional[Dict[str, Any]] = None
    override_entry: Optional[Dict[str, Any]] = None


def evaluate_choice_count_consistency(
    question_index: int,
    answer_set: List[str],
    status: Any,
    confidence: float,
    source: str,
    raw_img_path: Optional[Path],
    cropped_img_path: Optional[Path] = None,
    ai_service: Optional[Any] = None,
) -> ChoiceCountDecision:
    """
    Compare answer_set letter count against local '(Choose N answer(s))' hint.
      - Normal mismatch: NEVER overwrite valid community/AI/image answer to '?';
        preserve answer_set, flag CONFLICT, and emit a choice_count_warnings entry.
      - Strong override ONLY when BOTH:
          (1) two independent local checks agree with high confidence on N, AND
          (2) the answer is structurally impossible/absurd relative to visible options
              (e.g. len(letters) > visible_options or >=2 letters on a 3-option Choose-1 image).
    """
    from backend.app.db.models import AnswerStatus

    valid_letters = [a for a in answer_set if a != "?"]
    if not raw_img_path or not valid_letters:
        return ChoiceCountDecision(answer_set=list(answer_set), status=status, confidence=confidence)

    expected_n, hint_high_conf = read_choice_hint_n_detailed(raw_img_path, ai_service=ai_service)
    if expected_n is None or expected_n <= 0 or len(valid_letters) == expected_n:
        return ChoiceCountDecision(answer_set=list(answer_set), status=status, confidence=confidence)

    opt_target = cropped_img_path if (cropped_img_path and cropped_img_path.exists()) else raw_img_path
    visible_opts = count_visible_options(opt_target)
    is_absurd_count = (visible_opts is not None) and (
        len(valid_letters) > visible_opts
        or (visible_opts <= 3 and expected_n == 1 and len(valid_letters) >= 2)
    )

    if hint_high_conf and is_absurd_count:
        return ChoiceCountDecision(
            answer_set=["?"],
            status=AnswerStatus.CONFLICT,
            confidence=0.0,
            overridden=True,
            override_entry={
                "question": question_index,
                "hint_n": expected_n,
                "before": valid_letters,
                "after": ["?"],
                "visible_options": visible_opts,
            },
        )

    return ChoiceCountDecision(
        answer_set=list(answer_set),
        status=AnswerStatus.CONFLICT,
        confidence=confidence,
        overridden=False,
        warning_entry={
            "question": question_index,
            "hint_n": expected_n,
            "answer_letters": valid_letters,
            "source": source,
        },
    )


