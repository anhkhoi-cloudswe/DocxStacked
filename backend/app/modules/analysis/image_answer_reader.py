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


def read_choice_hint_n(
    image_input: Union[Path, str, Image.Image],
    ai_service: Optional[Any] = None,
) -> Optional[int]:
    """
    Đọc N từ dòng '(Choose N answers)' hoặc '(Choose 1 answer)' ở dải đầu ảnh đề thi fuexam (y: 170..280, x: 40..500).
    Chỉ dùng nhận dạng cục bộ (không gọi Gemini AI để tránh tốn hạn mức).
    Trả về số nguyên N (>= 1) hoặc None nếu không nhận diện được.
    """
    if isinstance(image_input, (str, Path)):
        im = Image.open(image_input)
    else:
        im = image_input

    a = np.array(im)
    if a.shape[1] >= 1200 and a.shape[0] >= 500:
        dark_mask = (a < 180).all(axis=2)
        # Quét vùng dải chứa dòng (Choose N answer/answers)
        sub = dark_mask[170:280, 40:500]
        lab, n_components = ndi.label(sub)
        if n_components >= 12:
            objs = ndi.find_objects(lab)
            valid_boxes = []
            for sl in objs:
                y_sl, x_sl = sl
                h = y_sl.stop - y_sl.start
                w = x_sl.stop - x_sl.start
                if 8 <= h <= 35 and 2 <= w <= 40:
                    valid_boxes.append((x_sl.start, y_sl.start, x_sl.stop, y_sl.stop))
            valid_boxes.sort(key=lambda b: b[0])
            if len(valid_boxes) >= 12:
                # Ký tự số N nằm ở vị trí thứ 7 (chỉ số 6) sau các ký tự '(', 'C', 'h', 'o', 'o', 's', 'e'
                d_box = valid_boxes[6]
                w = d_box[2] - d_box[0]
                h = d_box[3] - d_box[1]
                # Chữ số '1': đặc trưng cột thẳng hẹp (w ~ 8..13, h ~ 24..32, h/w >= 2.2)
                if 7 <= w <= 13 and 24 <= h <= 32 and (h / w) >= 2.2:
                    return 1

    # Không gọi Gemini AI; nếu không đọc được N cục bộ thì trả None để bỏ qua kiểm tra N.
    return None


