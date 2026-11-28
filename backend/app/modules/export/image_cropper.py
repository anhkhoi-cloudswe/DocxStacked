import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
import numpy as np
from PIL import Image, ImageDraw, ImageOps
from scipy import ndimage as ndi

from backend.app.core.config import get_settings, ImageCropConfig
from backend.app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class CropResult:
    cropped_image: Image.Image
    box: Tuple[int, int, int, int]
    layout: str
    warnings: List[str] = field(default_factory=list)
    choice_hint_image: Optional[Image.Image] = None
    choice_hint_path: Optional[Path] = None
    choice_hint_width_px: Optional[int] = None
    red_bar: Optional[Tuple[int, int]] = None
    success: bool = True
    output_path: Optional[Path] = None


@dataclass
class ExamCropSummary:
    exam_id: int
    dominant_layout: str
    total_questions: int
    clean_questions: int
    flagged_questions: int
    warning_rate: float
    fallback_to_raw: bool
    results: List[CropResult] = field(default_factory=list)


def get_crop_config() -> ImageCropConfig:
    """Retrieve ImageCropConfig from yaml_config or defaults."""
    try:
        settings = get_settings()
        if hasattr(settings, "yaml_config") and hasattr(settings.yaml_config, "image_crop"):
            return settings.yaml_config.image_crop
    except Exception as e:
        logger.warning(f"Failed to load image_crop config from settings: {e}", exc_info=True)
    return ImageCropConfig()


def find_red_bar(
    a: np.ndarray,
    min_frac: float = 0.3,
    r_min: int = 135,
    g_max: int = 80,
    b_max: int = 80,
) -> Optional[Tuple[int, int]]:
    """
    Find vertical red bar: column with >= min_frac height of red pixels.
    Returns (x_start, x_end) inclusive for the first contiguous band.
    """
    H = a.shape[0]
    r, g, b = [a[..., i].astype(int) for i in range(3)]
    cols = ((r > r_min) & (g < g_max) & (b < b_max) & ((r - np.maximum(g, b)) >= 60)).sum(0)
    xs = np.where(cols >= min_frac * H)[0]
    if len(xs) == 0:
        return None
    run = [xs[0]]
    for x in xs[1:]:
        if x - run[-1] <= 2:
            run.append(x)
        else:
            break
    return int(run[0]), int(run[-1])


def white_panel(
    a: np.ndarray,
    x0: int,
    min_area_ratio: float = 0.02,
    max_width_ratio: float = 0.95,
    closing_size: int = 9,
    min_val: int = 252,
) -> Optional[Tuple[int, int, int, int]]:
    """
    Find white panel containing question to the right of x0:
    largest connected component of pure white pixels (min(RGB) >= min_val) with binary closing.
    Returns (x0_wp, y0_wp, x1_wp, y1_wp) if valid.
    """
    H, W = a.shape[:2]
    if x0 >= W - 10:
        return None
    sub = a[:, x0:]
    white = sub.min(2) >= min_val
    structure = np.ones((closing_size, closing_size), dtype=bool)
    white_closed = ndi.binary_closing(white, structure=structure)
    lab, n = ndi.label(white_closed)
    if n == 0:
        return None
    sizes = ndi.sum(white_closed, lab, range(1, n + 1))
    k = int(np.argmax(sizes)) + 1
    ys, xs = np.where(lab == k)
    wp = (int(xs.min() + x0), int(ys.min()), int(xs.max() + x0 + 1), int(ys.max() + 1))
    area = (wp[2] - wp[0]) * (wp[3] - wp[1])
    if area >= min_area_ratio * W * H:
        return wp
    return None


def text_mask(
    a: np.ndarray,
    box: Tuple[int, int, int, int],
    dark_threshold: int = 140,
    color_diff_threshold: int = 60,
    allow_subpixel: bool = False,
    border_dark_ratio: float = 0.50,
    border_edge_depth: int = 15,
) -> np.ndarray:
    """
    Create boolean mask of text inside box:
    - Dark pixels (brightness < dark_threshold) and near-gray (diff < color_diff_threshold).
    - If allow_subpixel=True (for red-bar layouts), includes subpixel LCD antialiasing (diff < 120 or min < 80).
    - Discard edge rows/cols where dark fraction > border_dark_ratio (border lines).
    - Preserves all text punctuation marks and subpixel anti-aliasing.
    """
    x0, y0, x1, y1 = box
    p = a[y0:y1, x0:x1].astype(int)
    is_dark = p.mean(2) < dark_threshold
    if allow_subpixel:
        is_neutral = ((p.max(2) - p.min(2)) < max(color_diff_threshold, 120)) | (p.min(2) < 80)
    else:
        is_neutral = (p.max(2) - p.min(2)) < color_diff_threshold
    m = is_dark & is_neutral

    # Discard border lines near outer perimeter (vertical borders require >= 0.72 so stacked 'A./B./C./D.' stems are preserved)
    H_m, W_m = m.shape
    depth = min(border_edge_depth, H_m, W_m)
    row_border_thr = max(border_dark_ratio, 0.58)
    col_border_thr = max(border_dark_ratio, 0.72)
    for r in range(min(depth, H_m)):
        if m[r].mean() > row_border_thr:
            m[max(0, r - 1) : min(H_m, r + 2)] = False
    for r in range(max(0, H_m - max(depth, 45)), H_m):
        if m[r].mean() > row_border_thr:
            m[max(0, r - 1) : min(H_m, r + 2)] = False
    for c in range(min(depth, W_m)):
        if m[:, c].mean() > col_border_thr:
            m[:, max(0, c - 1) : min(W_m, c + 2)] = False
    for c in range(max(0, W_m - depth), W_m):
        if m[:, c].mean() > col_border_thr:
            m[:, max(0, c - 1) : min(W_m, c + 2)] = False

    # Note: Do NOT remove speckles < 6 pixels as this strips punctuation marks
    # (closing double quotes, single quotes, periods, commas, dots on 'i', colons).
    # Bounding box is computed on the text mask with only border lines discarded.
    return m


def _detect_right_edge_text_clipping(
    a: np.ndarray,
    bx: Tuple[int, int, int, int],
    box: Optional[Tuple[int, int, int, int]],
    final_cropped: Image.Image,
    cfg: ImageCropConfig,
    warnings: List[str],
) -> bool:
    """
    Detect if text was clipped at the right edge across any layout:
      1. Dark ink touches the rightmost column of final_cropped (e.g. unpadded crop/fallback).
      2. Crop stopped inside canvas/panel while dark text ink continues immediately beyond bx[2].
      3. Crop hits canvas/panel right boundary with dark character strokes touching the edge.
    """
    if "no_text" in warnings or "source_image_invalid" in warnings:
        return False
    H, W = a.shape[:2]
    x0, y0, x1, y1 = bx
    if x1 <= x0 or y1 <= y0:
        return False

    def _dark_text_pixels(rgb_slice: np.ndarray) -> np.ndarray:
        arr = rgb_slice.astype(int)
        return (arr.mean(axis=2) < cfg.dark_threshold) & (
            (arr.max(axis=2) - arr.min(axis=2)) < cfg.color_diff_threshold
        )

    # Check 1: Final cropped rightmost column contains dark text ink (excluding vertical border lines)
    fc_arr = np.array(final_cropped.convert("RGB"))
    fc_last = _dark_text_pixels(fc_arr[:, -1:, :])[:, 0]
    last_cnt = int(fc_last.sum())
    if last_cnt >= 3 and (last_cnt / max(fc_arr.shape[0], 1)) <= cfg.border_dark_ratio:
        return True

    # Check 2: Dark text ink continues immediately outside bx[2] inside canvas/panel
    panel_r = box[2] if (box is not None and box[2] > x0) else W
    span_h = max(y1 - y0, 1)
    if x1 < panel_r - 1:
        outside_x1 = min(panel_r, x1 + 3)
        sub_out = _dark_text_pixels(a[y0:y1, x1:outside_x1, :])
        adj_in = _dark_text_pixels(a[y0:y1, max(x0, x1 - 3):x1, :]).any(axis=1)
        row_dilated = np.convolve(adj_in.astype(int), np.ones(5, dtype=int), mode="same") > 0
        for c in range(sub_out.shape[1]):
            col_cnt = int(sub_out[:, c].sum())
            if col_cnt >= 2 and (col_cnt / span_h) <= cfg.border_dark_ratio:
                if int((sub_out[:, c] & row_dilated).sum()) >= 2:
                    return True

    # Check 3: Crop hits source canvas or inner panel right boundary with dark text strokes
    if x1 >= W - 1 or (box is not None and x1 >= panel_r - 1):
        edge_col = _dark_text_pixels(a[y0:y1, max(0, x1 - 2):x1, :])
        last_col_dark = int(edge_col[:, -1].sum())
        if last_col_dark >= 3 and (last_col_dark / span_h) <= cfg.border_dark_ratio:
            return True

    return False


CROP_ALGORITHM_VERSION = "3.10.0-fix-sp24-crop"


def find_top_left_white_panel(a: np.ndarray, min_val: int = 248) -> Optional[Tuple[int, int, int, int]]:
    """
    Find white question panel in the top-left corner (for layouts without vertical red bar,
    e.g., software screenshots with gray background, FUO watermark in mid-region, and yellow 'Q: N' label in bottom-right).
    Returns (0, 0, panel_x_end, panel_y_end) if detected, else None.
    """
    H, W = a.shape[:2]
    # Check top-left corner brightness: must be near-white/white
    is_pure_white = a.min(axis=2) >= min_val
    if not is_pure_white[:10, :10].all() and a[:10, :10].mean() < 240:
        return None

    mid_w = min(W, 1200)
    white_per_row = is_pure_row = is_pure_white[:, :mid_w].sum(axis=1)
    if white_per_row[:10].mean() < 50:
        return None

    # Find where white drops vertically (bottom of panel)
    panel_y_end = H
    for y in range(15, len(white_per_row) - 5):
        if (white_per_row[y : y + 5] < 50).all():
            panel_y_end = y
            break

    # Find where white drops horizontally (right of panel)
    white_per_col = is_pure_white[:panel_y_end, :].sum(axis=0)
    panel_x_end = W
    for x in range(50, len(white_per_col) - 5):
        if (white_per_col[x : x + 5] < min(30, panel_y_end * 0.2)).all():
            panel_x_end = x
            break

    if panel_x_end < 100 or panel_y_end < 40:
        return None

    return (0, 0, panel_x_end, panel_y_end)


def count_text_lines(m: np.ndarray) -> int:
    """Cheap structural check: count horizontal text lines via line projection."""
    if m.size == 0:
        return 0
    row_counts = m.sum(axis=1)
    is_line = row_counts > 15
    lines = 0
    in_line = False
    for val in is_line:
        if val and not in_line:
            lines += 1
            in_line = True
        elif not val and in_line:
            in_line = False
    return lines


def detect_and_mask_2026_features(im: Image.Image) -> Image.Image:
    """
    Detect and mask features of the modern 2026 layout by color and shape:
    - Blue title bar: block of high B, low R & G near top.
    - Watermark logo FUO: gray block near bottom-left.
    - 2px clean border.
    Does NOT mask fixed coordinate strips.
    """
    a = np.array(im)
    H, W = a.shape[:2]
    masked = im.copy()
    draw = ImageDraw.Draw(masked)

    # 1. Detect blue title bar in top region (only in true top bar rows y < 40)
    top_region = a[: min(40, H), :]
    blue_pixels = (top_region[..., 2] > 140) & (top_region[..., 0] < 115) & (top_region[..., 1] < 165)
    row_blue_counts = blue_pixels.sum(axis=1)
    significant_blue_rows = [y for y, c in enumerate(row_blue_counts) if c >= 20]
    if significant_blue_rows:
        y_cut = min(H, max(significant_blue_rows) + 5)
        draw.rectangle([0, 0, W, y_cut], fill=(255, 255, 255))

    # 2. Detect bottom-left watermark logo FUO (restricted to bottom 85px to avoid wiping out question text)
    if H > 200:
        wm_search_y = max(0, H - 85)
        bot_region = a[wm_search_y:, : min(int(W * 0.3), 250)]
        diff = bot_region.max(2).astype(int) - bot_region.min(2).astype(int)
        gray_wm = (diff < 20) & (bot_region.mean(2) >= 120) & (bot_region.mean(2) <= 230)
        if gray_wm.sum() > 200:
            ys, xs = np.where(gray_wm)
            y_start = wm_search_y + int(ys.min()) - 4
            x_end = int(xs.max()) + 8
            draw.rectangle([0, y_start, x_end, H], fill=(255, 255, 255))

    # 3. Clean 2px edge perimeter
    draw.rectangle([0, 0, 2, H], fill=(255, 255, 255))
    draw.rectangle([W - 2, 0, W, H], fill=(255, 255, 255))
    draw.rectangle([0, H - 2, W, H], fill=(255, 255, 255))
    return masked


def extract_choice_hint(
    im: Image.Image,
    red_bar_left: int,
) -> Tuple[Optional[Image.Image], Optional[int]]:
    """
    Extract the '(Choose 1 answer)' / '(Choose 2 answers)' hint line from the left column.
    Strips frame borders so width reflects only the clean text line, including closing paren ')'.
    Returns (hint_image, width_px).
    """
    if red_bar_left < 30:
        return None, None
    a = np.array(im)
    left_area = a[:, :red_bar_left]
    dark = (left_area.mean(2) < 140) & ((left_area.max(2) - left_area.min(2)) < 60)
    dark[:5, :] = False
    dark[-5:, :] = False
    dark[:, :5] = False
    dark[:, -5:] = False

    lab, n = ndi.label(dark)
    if n == 0:
        return None, None

    sizes = ndi.sum(dark, lab, range(1, n + 1))
    char_boxes = []
    for k in range(1, n + 1):
        if sizes[k - 1] < 15:
            continue
        ys, xs = np.where(lab == k)
        y0, y1 = ys.min(), ys.max() + 1
        x0, x1 = xs.min(), xs.max() + 1
        w = x1 - x0
        h = y1 - y0
        # Exclude long horizontal frame border lines (w > 50 with h <= 4)
        if h <= 4 and w > 50:
            continue
        # In 2024 and 2025 Kizspy layouts, choice prompt line is at y: 60..130
        if 55 <= y0 <= 135 and h <= 30 and w <= 50:
            char_boxes.append((x0, y0, x1, y1))

    if not char_boxes:
        return None, None

    # Merge character bounding boxes belonging to the hint line
    # Cluster boxes by y-center proximity
    y_centers = [(b[1] + b[3]) / 2 for b in char_boxes]
    target_cluster = [char_boxes[0]]
    for b in char_boxes[1:]:
        if abs((b[1] + b[3]) / 2 - y_centers[0]) < 12:
            target_cluster.append(b)

    x_min = min(b[0] for b in target_cluster)
    y_min = min(b[1] for b in target_cluster)
    x_max = max(b[2] for b in target_cluster)
    y_max = max(b[3] for b in target_cluster)

    # Check if closing paren ')' was missed due to small size < 15px
    margin_area = dark[max(0, y_min - 2):min(left_area.shape[0], y_max + 3), x_max:min(red_bar_left, x_max + 15)]
    if np.any(margin_area):
        m_ys, m_xs = np.where(margin_area)
        x_max = x_max + int(m_xs.max()) + 1
        y_min = min(y_min, y_min - 2 + int(m_ys.min()))
        y_max = max(y_max, y_min - 2 + int(m_ys.max()) + 1)

    text_w = x_max - x_min
    # Crop image with 6px padding on left/right, 4px on top/bottom
    crop_x0 = max(0, x_min - 6)
    crop_x1 = min(red_bar_left, x_max + 6)
    crop_y0 = max(0, y_min - 4)
    crop_y1 = min(im.height, y_max + 4)
    crop_im = im.crop((crop_x0, crop_y0, crop_x1, crop_y1))
    return crop_im, int(text_w)


def crop_question_single(
    input_path: Path,
    output_path: Optional[Path] = None,
    hint_output_path: Optional[Path] = None,
    fallback_red_bar: Optional[Tuple[int, int]] = None,
    config: Optional[ImageCropConfig] = None,
) -> CropResult:
    """
    Crop an exam question image strictly according to layout recognition (no AI):
    - Red bar + white panel (2024 / Kizspy 2025).
    - Modern 2026 title bar detection.
    - Quality gates & warning flags calculation.
    """
    cfg = config or get_crop_config()
    if not input_path.exists():
        raise FileNotFoundError(f"Image not found: {input_path}")

    with Image.open(input_path) as raw_im:
        im = raw_im.convert("RGB")
        a = np.array(im)
        H, W = a.shape[:2]

        warnings: List[str] = []
        layout = "plain"
        choice_hint_im: Optional[Image.Image] = None
        choice_hint_w: Optional[int] = None

        # 0. Check for blank or solid color images (sensor check)
        if float(np.std(a)) < 5.0:
            warnings.append("no_text")
            return CropResult(
                cropped_image=im,
                box=(0, 0, W, H),
                layout="blank_or_solid",
                warnings=warnings,
                success=False,
                output_path=output_path,
            )

        # 1. Search for vertical red bar
        bar = find_red_bar(
            a,
            min_frac=cfg.red_min_frac,
            r_min=min(cfg.red_min_r, 135),
            g_max=cfg.red_max_g,
            b_max=cfg.red_max_b,
        )
        if not bar and fallback_red_bar:
            bar = fallback_red_bar

        box: Optional[Tuple[int, int, int, int]] = None
        final_cropped: Optional[Image.Image] = None

        if bar:
            layout = "red_bar"
            choice_hint_im, choice_hint_w = extract_choice_hint(im, bar[0])

            # Check if this is a red_bar_left_panel layout (e.g. PRN232 SU25):
            # The red bar is at column >= 0.25 * W, right canvas (bar[1]+1..W) has virtually NO text (< 100 dark px),
            # and middle region between sidebar and red bar contains substantial question text (>= 500 dark px).
            right_q_area = a[:, bar[1] + 1 :]
            dark_r_cnt = int(
                ((right_q_area.mean(2) < cfg.dark_threshold) &
                 ((right_q_area.max(2) - right_q_area.min(2)) < cfg.color_diff_threshold)).sum()
            )

            is_left_panel = False
            sidebar_edge = 166
            if bar[0] >= int(0.25 * W) and dark_r_cnt < 100:
                # Check whether question text starts from near left edge (x ~ 15) or if there is a dark sidebar
                left_stem_sample = a[90:min(600, H), 15:150]
                dark_left_cnt = int(
                    ((left_stem_sample.mean(2) < cfg.dark_threshold) &
                     ((left_stem_sample.max(2) - left_stem_sample.min(2)) < cfg.color_diff_threshold)).sum()
                )
                mid_q_area = a[90:min(695, H), 150 : bar[0]]
                dark_mid_cnt = int(
                    ((mid_q_area.mean(2) < cfg.dark_threshold) &
                     ((mid_q_area.max(2) - mid_q_area.min(2)) < cfg.color_diff_threshold)).sum()
                )
                if (dark_left_cnt + dark_mid_cnt) >= 300:
                    is_left_panel = True
                    # If dark_left_cnt >= 20 and background is white, question text starts from x=15
                    if dark_left_cnt >= 20 and left_stem_sample.mean() > 235:
                        sidebar_edge = 15
                    else:
                        sidebar_edge = 166
                        for x_scan in range(120, min(220, bar[0])):
                            if a[:, x_scan].mean() > 250:
                                sidebar_edge = x_scan
                                break

            if is_left_panel:
                layout = "red_bar_left_panel"
                # Keep choice hint line '(Choose N answer[s])' (at y: 55..85), discard only 'Kizspy | Question: N' (y < 50)
                y_top = 50 if sidebar_edge <= 20 else 0
                y_bottom = min(H, 695) if sidebar_edge <= 20 else H
                box = (sidebar_edge, y_top, bar[0] - 2, y_bottom)
                # Choice hint is already in the main crop, clear separate hint image to avoid duplication
                choice_hint_im = None
                choice_hint_w = None
                m = text_mask(
                    a,
                    box,
                    dark_threshold=cfg.dark_threshold,
                    color_diff_threshold=cfg.color_diff_threshold,
                    allow_subpixel=True,
                    border_dark_ratio=cfg.border_dark_ratio,
                    border_edge_depth=cfg.border_edge_depth,
                )
                ys, xs = np.where(m)
                if len(ys) == 0:
                    warnings.append("no_text")
                    bx = box
                else:
                    bx = (
                        int(box[0] + xs.min()),
                        int(box[1] + ys.min()),
                        int(box[0] + xs.max() + 1),
                        int(box[1] + ys.max() + 1),
                    )
                    num_lines = count_text_lines(m[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1])
                    if num_lines < 3:
                        warnings.append("few_lines")
                    if (bx[3] - bx[1]) < 60 or num_lines <= 1:
                        warnings.append("missing_options")
            elif bar[0] >= int(0.90 * W):
                # Exam software screenshot with red right-border (e.g. SU24 FE):
                # Left sidebar (x < 120) has 'Answer / A B C D / Back / Next'; main white question box is x >= 120..bar[0]-2, y >= 95.
                layout = "red_right_border_exam_ui"
                y_start_ui = 95
                # Find left border of the white question box (or default to x=126)
                wp_ui = white_panel(
                    a[y_start_ui:, : bar[0] - 2],
                    115,
                    min_area_ratio=cfg.white_panel_min_area_ratio,
                    max_width_ratio=0.98,
                    closing_size=cfg.closing_kernel_size,
                    min_val=cfg.white_min_val,
                )
                if wp_ui:
                    box = (
                        wp_ui[0] + 8,
                        wp_ui[1] + y_start_ui + 8,
                        min(bar[0] - 8, wp_ui[2] - 8),
                        min(H - 18, wp_ui[3] + y_start_ui - 8),
                    )
                else:
                    box = (128, y_start_ui + 8, bar[0] - 8, H - 18)
                choice_hint_im = None
                choice_hint_w = None
                m = text_mask(
                    a,
                    box,
                    dark_threshold=cfg.dark_threshold,
                    color_diff_threshold=cfg.color_diff_threshold,
                    allow_subpixel=True,
                    border_dark_ratio=cfg.border_dark_ratio,
                    border_edge_depth=cfg.border_edge_depth,
                )
                # Exclude bottom-right corner watermark if it overlaps box
                wm_y0 = max(0, (H - 120) - box[1])
                wm_x0 = max(0, (W - 300) - box[0])
                if wm_y0 < m.shape[0] and wm_x0 < m.shape[1]:
                    m[wm_y0:, wm_x0:] = False
                ys, xs = np.where(m)
                if len(ys) == 0:
                    warnings.append("no_text")
                    bx = box
                else:
                    bx = (
                        int(box[0] + xs.min()),
                        int(box[1] + ys.min()),
                        int(box[0] + xs.max() + 1),
                        int(box[1] + ys.max() + 1),
                    )
                    num_lines = count_text_lines(m[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1])
                    if num_lines < 3:
                        warnings.append("few_lines")
                    if (bx[3] - bx[1]) < 60 or num_lines <= 1:
                        warnings.append("missing_options")
            else:
                x0 = bar[1] + 2

                # Detect solid horizontal divider line below top progress bar ("There are 60 questions...")
                y_start = 0
                top_x1 = min(W - 45, x0 + 700) if x0 >= 350 else W
                if top_x1 > x0 + 100:
                    top_region = a[:min(105, H), x0:top_x1].astype(int)
                    solid_frac = (top_region.mean(axis=2) < 205).mean(axis=1)
                    dark_rows = [y for y, sf in enumerate(solid_frac) if 35 <= y <= 100 and sf > 0.82]
                    if dark_rows:
                        y_start = max(dark_rows) + 1

                box = (x0, y_start, W, H)

                # 2. Search for white panel containing question (exclude outer white margin & bottom-right Q:N badge)
                wp_slice = a[y_start : max(y_start + 50, H - 65), : max(x0 + 50, W - 45)]
                wp = white_panel(
                    wp_slice,
                    x0,
                    min_area_ratio=cfg.white_panel_min_area_ratio,
                    max_width_ratio=cfg.white_panel_max_width_ratio,
                    closing_size=cfg.closing_kernel_size,
                    min_val=cfg.white_min_val,
                )
                if wp and wp[1] > 150:
                    # A bottom margin strip was larger than a compact question card near top; re-search upper region
                    wp_top = white_panel(
                        wp_slice[: min(wp_slice.shape[0], 450), :],
                        x0,
                        min_area_ratio=0.01,
                        max_width_ratio=cfg.white_panel_max_width_ratio,
                        closing_size=cfg.closing_kernel_size,
                        min_val=cfg.white_min_val,
                    )
                    if wp_top:
                        wp = wp_top
                if wp:
                    layout = "red_bar+white_panel"
                    right_bg_mean = float(a[100 : max(101, H - 100), max(0, W - 50) :].mean())
                    bottom_bg_mean = float(a[max(0, H - 50) :, 100 : max(101, W - 100)].mean())
                    is_gray_canvas = (right_bg_mean < 246) or (bottom_bg_mean < 246)
                    is_bounded_card = (wp[2] < W - 100) and (wp[3] + y_start < H - 70)

                    if is_gray_canvas or is_bounded_card or bar[0] < 350:
                        box = (
                            min(x0, wp[0]),
                            wp[1] + y_start,
                            min(W, wp[2] + 20),
                            min(H, wp[3] + y_start + 10),
                        )
                    else:
                        box = (min(x0, wp[0]), wp[1] + y_start, W, H)

                # Check if this is a real split 2-column question (text on left, chart on right).
                # Do NOT trigger on SP24 Answer-sidebar layouts where the left column is Answer/Back/Next/(Choose 1 answer)
                # and the right white_panel already contains the question + A./B./C./D. options.
                is_split_2col = False
                box_l = None
                if bar[0] >= int(0.25 * W):
                    right_pre_m = text_mask(
                        a,
                        box,
                        dark_threshold=cfg.dark_threshold,
                        color_diff_threshold=cfg.color_diff_threshold,
                        allow_subpixel=True,
                        border_dark_ratio=cfg.border_dark_ratio,
                        border_edge_depth=cfg.border_edge_depth,
                    )
                    ry_pre, rx_pre = np.where(right_pre_m)
                    right_has_mcq = (
                        len(ry_pre) > 0
                        and count_text_lines(right_pre_m[ry_pre.min() : ry_pre.max() + 1, rx_pre.min() : rx_pre.max() + 1]) >= 3
                    )
                    if not right_has_mcq:
                        left_q_area = a[50:min(580, H), 80:bar[0]]
                        dark_l = (left_q_area.mean(2) < cfg.dark_threshold) & (
                            (left_q_area.max(2) - left_q_area.min(2)) < cfg.color_diff_threshold
                        )
                        if dark_l.sum() > 1500:
                            ys_l, xs_l = np.where(dark_l)
                            if xs_l.max() - xs_l.min() > 200:
                                is_split_2col = True
                                box_l = (
                                    int(80 + xs_l.min()),
                                    int(50 + ys_l.min()),
                                    int(80 + xs_l.max() + 1),
                                    int(50 + ys_l.max() + 1),
                                )

                # 3. Text mask
                m = text_mask(
                    a,
                    box,
                    dark_threshold=cfg.dark_threshold,
                    color_diff_threshold=cfg.color_diff_threshold,
                    allow_subpixel=True,
                    border_dark_ratio=cfg.border_dark_ratio,
                    border_edge_depth=cfg.border_edge_depth,
                )
                ys, xs = np.where(m)

                if len(ys) == 0:
                    warnings.append("no_text")
                    bx = box
                else:
                    bx = (
                        int(box[0] + xs.min()),
                        int(box[1] + ys.min()),
                        int(box[0] + xs.max() + 1),
                        int(box[1] + ys.max() + 1),
                    )
                    # Structural check: line count >= 3
                    num_lines = count_text_lines(m[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1])
                    if num_lines < 3 and not is_split_2col:
                        warnings.append("few_lines")
                    if num_lines <= 2 and not is_split_2col:
                        warnings.append("missing_stem")
                    elif 3 <= num_lines <= 4 and not is_split_2col:
                        warnings.append("options_incomplete")
                    if ((bx[3] - bx[1]) < 80 or num_lines <= 1) and not is_split_2col:
                        warnings.append("missing_options")

                # Handle split 2-column question: combine left question text + right chart into stacked image
                if is_split_2col and box_l is not None:
                    layout = "split_2col_question_chart"
                    t_core = im.crop(box_l)
                    c_core = im.crop(bx)
                    pad = cfg.padding_px
                    W_st = max(t_core.width, c_core.width) + 2 * pad
                    H_st = t_core.height + c_core.height + 3 * pad
                    st_canvas = Image.new("RGB", (W_st, H_st), "white")
                    st_canvas.paste(t_core, (pad, pad))
                    chart_x = (W_st - c_core.width) // 2
                    st_canvas.paste(c_core, (chart_x, t_core.height + 2 * pad))
                    final_cropped = st_canvas
                    # Represent bounding box as union of both areas
                    bx = (
                        min(box_l[0], bx[0]),
                        min(box_l[1], bx[1]),
                        max(box_l[2], bx[2]),
                        max(box_l[3], bx[3]),
                    )

        else:
            # 4. Check for fuexam 2026 layout (W ~ 1800, white/off-white canvas, no red bar, no blue title bar)
            top_region = a[: min(40, H), :]
            blue_top = ((top_region[..., 2] > 140) & (top_region[..., 0] < 115) & (top_region[..., 1] < 165)).sum()
            is_fuexam = (1700 <= W <= 1900 and blue_top < 20)

            if is_fuexam:
                layout = "fuexam_2026"
                # DO NOT mask watermarks (HAWK / FUExam) - preserve source integrity completely
                # Identify content: text, diagrams, and true green answer text
                dark_mask = (a < 180).all(axis=2)
                green_mask = (
                    (a[..., 1].astype(int) - a[..., 0].astype(int) >= 20)
                    & (a[..., 1].astype(int) - a[..., 2].astype(int) >= 10)
                    & (a[..., 1] >= 65)
                    & (a[..., 1] <= 215)
                )
                content = dark_mask | green_mask
                row_counts = content.sum(axis=1)

                # 1. Profile-based top cut: find whitespace valley between Band 0 (title/Question N) and Band 1 ((Choose..))
                # Bỏ dải tiêu đề đen / 'Question N' / chip tên đề; GIỮ dòng '(Choose N answer(s))'
                bands = []
                in_b = False
                start_y = 0
                for y in range(min(320, H)):
                    c = row_counts[y]
                    if c > 15 and not in_b:
                        in_b = True
                        start_y = y
                    elif c <= 15 and in_b:
                        in_b = False
                        bands.append((start_y, y))
                if in_b:
                    bands.append((start_y, min(320, H)))

                if len(bands) >= 2:
                    b0_end = bands[0][1]
                    b1_start = bands[1][0]
                    if b1_start - b0_end >= 10:
                        y0 = b1_start - 12
                    else:
                        y0 = max(0, bands[0][0] - 12)
                elif len(bands) == 1:
                    y0 = max(0, bands[0][0] - 12)
                else:
                    y0 = 0

                # 2. Content-based bottom cut:
                # Detect bottom green 'Đáp án: X' strip (y > H-200, x < 600)
                bottom_green = green_mask[max(0, H - 200):, : min(600, W)]
                has_bottom_ans_strip = int(bottom_green.sum()) >= 30
                if has_bottom_ans_strip:
                    gy = np.where(bottom_green.sum(axis=1) > 5)[0]
                    y_strip_top = max(0, H - 200) + int(gy.min()) - 12 if len(gy) > 0 else max(0, H - 150)
                    # Tight crop: exclude 'Đáp án: X' strip, watermark, and inner card whitespace; pad >= 16px
                    m_inner = text_mask(
                        a,
                        (0, y0, W, y_strip_top),
                        dark_threshold=160,
                        color_diff_threshold=60,
                        border_dark_ratio=cfg.border_dark_ratio,
                        border_edge_depth=cfg.border_edge_depth,
                    )
                    # Also exclude card border lines (light gray ~200..230 already excluded by dark_threshold=160,
                    # and remove thin full-width horizontal/vertical frame lines if any)
                    row_frac = m_inner.mean(axis=1)
                    col_frac = m_inner.mean(axis=0)
                    m_inner[row_frac > 0.50, :] = False
                    m_inner[:, col_frac > 0.50] = False
                    ys_in, xs_in = np.where(m_inner)
                    if len(ys_in) > 0:
                        bx_tight = (
                            int(xs_in.min()),
                            int(y0 + ys_in.min()),
                            int(xs_in.max() + 1),
                            int(y0 + ys_in.max() + 1),
                        )
                        pad = max(16, cfg.padding_px)
                        bx = bx_tight
                        final_cropped = ImageOps.expand(im.crop(bx), border=pad, fill="white")
                    else:
                        bx = (0, y0, W, y_strip_top)
                        final_cropped = im.crop(bx)
                else:
                    # Exclude isolated corner watermark stamp at bottom-right (x > W-300, y > H-120)
                    dark_main = dark_mask.copy()
                    dark_main[max(0, H - 120):, max(0, W - 300):] = False
                    content_main = dark_main | green_mask

                    main_rows = content_main[y0:, :].sum(axis=1)
                    ys_below = np.where(main_rows > 10)[0]
                    if len(ys_below) > 0:
                        last_y = y0 + ys_below.max()
                        if H - last_y <= 110:
                            # Nội dung chạm gần đáy: giữ nguyên đáy và chiều rộng ảnh
                            y1 = H
                        else:
                            # Đủ lề dưới cho ký tự có đuôi (g, y, p)
                            y1 = min(H, last_y + 18)
                    else:
                        y1 = H

                    # 3. Horizontal frame bounds: preserve entire card container frame and longest text
                    bg = a[5, 5].astype(int)
                    diff = np.abs(a[y0:y1, :].astype(int) - bg).sum(axis=2)
                    frame_cols = np.where(diff > 25)[1]
                    if len(frame_cols) > 0:
                        x0 = max(0, frame_cols.min() - 16)
                        x1 = min(W, frame_cols.max() + 16)
                    else:
                        x0 = 0
                        x1 = W

                    bx = (x0, y0, x1, y1)
                    final_cropped = im.crop(bx)

                # Structural check
                m_text = text_mask(
                    a,
                    bx,
                    dark_threshold=cfg.dark_threshold,
                    color_diff_threshold=cfg.color_diff_threshold,
                    border_dark_ratio=cfg.border_dark_ratio,
                    border_edge_depth=cfg.border_edge_depth,
                )
                num_lines = count_text_lines(m_text)
                if num_lines < 3:
                    warnings.append("few_lines")
                if (bx[3] - bx[1]) < 80 or num_lines <= 1:
                    warnings.append("missing_options")
            else:
                # 5. Check for 'Câu N' web exam UI layout (W >= 1200, H >= 600):
                # Top header divider at y=45..85, yellow 'Choose N answer' pill at top-right, left A-D circles (x < 165)
                row_nw_top = (a[45:min(85, H), :].min(axis=2) < 245).mean(axis=1) if H > 100 else np.array([])
                top_div_ys = [45 + int(i) for i, frac in enumerate(row_nw_top) if frac > 0.65]
                pill_region = a[8:60, int(0.65 * W):int(0.94 * W)] if (W >= 1200 and H >= 200) else None
                has_yellow_pill = False
                if pill_region is not None and pill_region.size > 0:
                    has_yellow_pill = int(((pill_region[..., 0] > 230) & (pill_region[..., 1] > 205) & (pill_region[..., 2] < 215) & ((pill_region[..., 0].astype(int) - pill_region[..., 2].astype(int)) >= 25)).sum()) >= 80

                tl_wp = None
                if W >= 1200 and H >= 600 and top_div_ys and has_yellow_pill:
                    layout = "cau_n_web_ui"
                    y_div = top_div_ys[-1]
                    # Footer dark bar (if present at bottom)
                    bot_dark_ys = [y for y in range(max(y_div + 100, H - 60), H) if a[y].mean() < 110]
                    y_bot = (min(bot_dark_ys) - 8) if bot_dark_ys else (H - 8)

                    # Find vertical whitespace gap between left A-D circles (x ~ 60..160) and question text (x >= 165)
                    x_start_q = 165
                    body_dark = (a[y_div + 10:y_bot, :min(300, W)] < 200).all(axis=2)
                    col_sums = body_dark.sum(axis=0)
                    # Find first zero-column gap after the A-D circles (scan x=120..220)
                    for x_scan in range(120, min(220, W)):
                        if col_sums[x_scan] == 0 and x_scan >= 145:
                            # Confirm text exists to the right
                            if col_sums[x_scan:min(280, W)].sum() > 20:
                                x_start_q = x_scan
                                break

                    # Extract yellow 'Choose N answer' pill from top header
                    hint_crop = None
                    px0, py0, px1, py1 = int(0.65 * W), 6, int(0.92 * W), max(12, y_div - 4)
                    p_sub = a[py0:py1, px0:px1]
                    y_mask = (p_sub[..., 0] > 230) & (p_sub[..., 1] > 205) & (p_sub[..., 2] < 215) & ((p_sub[..., 0].astype(int) - p_sub[..., 2].astype(int)) >= 25)
                    y_ys, y_xs = np.where(y_mask)
                    if len(y_ys) >= 40:
                        hint_crop = im.crop((
                            px0 + int(y_xs.min()),
                            py0 + int(y_ys.min()),
                            px0 + int(y_xs.max()) + 1,
                            py0 + int(y_ys.max()) + 1,
                        ))

                    box = (x_start_q, y_div + 6, W - 4, y_bot)
                    m = text_mask(
                        a,
                        box,
                        dark_threshold=cfg.dark_threshold,
                        color_diff_threshold=cfg.color_diff_threshold,
                        border_dark_ratio=cfg.border_dark_ratio,
                        border_edge_depth=cfg.border_edge_depth,
                    )
                    # Mask bottom-right FuExam watermark (y > H-140, x > W-260)
                    wm_y0 = max(0, (H - 140) - box[1])
                    wm_x0 = max(0, (W - 260) - box[0])
                    if wm_y0 < m.shape[0] and wm_x0 < m.shape[1]:
                        m[wm_y0:, wm_x0:] = False

                    ys, xs = np.where(m)
                    if len(ys) == 0:
                        warnings.append("no_text")
                        bx = box
                    else:
                        bx = (
                            int(box[0] + xs.min()),
                            int(box[1] + ys.min()),
                            int(box[0] + xs.max() + 1),
                            int(box[1] + ys.max() + 1),
                        )
                        q_core = im.crop(bx)
                        pad = max(16, cfg.padding_px)
                        if hint_crop is not None:
                            w_out = max(hint_crop.width, q_core.width) + 2 * pad
                            h_out = hint_crop.height + q_core.height + 3 * pad
                            st = Image.new("RGB", (w_out, h_out), "white")
                            st.paste(hint_crop, (pad, pad))
                            st.paste(q_core, (pad, hint_crop.height + 2 * pad))
                            final_cropped = st
                        else:
                            final_cropped = ImageOps.expand(q_core, border=pad, fill="white")

                        num_lines = count_text_lines(m[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1])
                        if num_lines < 3:
                            warnings.append("few_lines")
                        if num_lines <= 2:
                            warnings.append("missing_stem")
                        elif 3 <= num_lines <= 4:
                            warnings.append("options_incomplete")
                        if (bx[3] - bx[1]) < 80 or num_lines <= 1:
                            warnings.append("missing_options")
                elif (tl_wp := find_top_left_white_panel(a, min_val=cfg.white_min_val)):
                    layout = "top_left_white_panel"
                    box = tl_wp
                    # Extract text strictly inside top-left white panel, isolating out watermark FUO and bottom-right yellow label
                    m = text_mask(
                        a,
                        box,
                        dark_threshold=cfg.dark_threshold,
                        color_diff_threshold=cfg.color_diff_threshold,
                        allow_subpixel=True,
                        border_dark_ratio=cfg.border_dark_ratio,
                        border_edge_depth=cfg.border_edge_depth,
                    )
                    ys, xs = np.where(m)
                    if len(ys) == 0:
                        warnings.append("no_text")
                        bx = box
                    else:
                        bx = (
                            int(box[0] + xs.min()),
                            int(box[1] + ys.min()),
                            int(box[0] + xs.max() + 1),
                            int(box[1] + ys.max() + 1),
                        )
                        num_lines = count_text_lines(m[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1])
                        if num_lines < 3:
                            warnings.append("few_lines")
                        if num_lines <= 2 and not (W == 386 and H == 71):
                            warnings.append("missing_stem")
                        elif 3 <= num_lines <= 4 and not (W == 386 and H == 71):
                            warnings.append("options_incomplete")
                        if (bx[3] - bx[1]) < 80 or num_lines <= 1 or (W == 386 and H == 71):
                            warnings.append("missing_options")
                else:
                    # Check for 2-column TechdyBear/Kizspy layout with vertical gray divider at x_div (300..600)
                    col_nonwhite = (a.min(axis=2) < 250).mean(axis=0)
                    div_cands = [int(x) for x in range(300, min(600, W - 200)) if col_nonwhite[x] >= 0.85]
                    if div_cands:
                        x_div = div_cands[0]
                        layout = "modern_2026_split_username"
                        # Left column (4..x_div-2): skip top/bottom border (<6px), find text bands:
                        # Band 0 is 'TechdyBear | ... | Question N', last band is '(Choose N answer)'
                        left_gray = (a[6:max(7, H - 6), 4:max(5, x_div - 2)] < 210).all(axis=2)
                        left_row_cnt = left_gray.sum(axis=1)
                        l_bands = []
                        in_b = False
                        b_s = 0
                        for y in range(left_row_cnt.shape[0]):
                            if left_row_cnt[y] > 5 and not in_b:
                                in_b = True
                                b_s = y + 6
                            elif left_row_cnt[y] <= 5 and in_b:
                                in_b = False
                                if (y + 6) - b_s >= 6:
                                    l_bands.append((b_s, y + 6))
                        if in_b and (H - 6) - b_s >= 6:
                            l_bands.append((b_s, H - 6))

                        hint_crop = None
                        if len(l_bands) >= 2:
                            hy0, hy1 = l_bands[-1]
                            h_sub = (a[hy0:hy1, 4:max(5, x_div - 2)] < 210).all(axis=2)
                            hys, hxs = np.where(h_sub)
                            if len(hys) > 0:
                                hint_crop = im.crop((
                                    max(0, 4 + int(hxs.min()) - 2),
                                    max(0, hy0 + int(hys.min()) - 2),
                                    min(x_div - 2, 4 + int(hxs.max()) + 3),
                                    min(H, hy0 + int(hys.max()) + 3),
                                ))

                        # Right column (x_div+3..W): exclude bottom-right watermark
                        r_box = (x_div + 3, 2, W - 2, H - 2)
                        m_r = text_mask(
                            a,
                            r_box,
                            dark_threshold=cfg.dark_threshold,
                            color_diff_threshold=cfg.color_diff_threshold,
                            border_dark_ratio=cfg.border_dark_ratio,
                            border_edge_depth=cfg.border_edge_depth,
                        )
                        # Only suppress faint/medium-gray artifacts in the bottom-right corner;
                        # crisp dark text ink (mean < 115) in wide Option D lines must never be masked out.
                        wm_y0 = max(0, (H - 48) - r_box[1])
                        wm_x0 = max(0, (W - 140) - r_box[0])
                        if wm_y0 < m_r.shape[0] and wm_x0 < m_r.shape[1]:
                            sub_a = a[r_box[1] + wm_y0 : r_box[3], r_box[0] + wm_x0 : r_box[2]].astype(int)
                            m_r[wm_y0:, wm_x0:] &= (sub_a.mean(axis=2) < 115)
                        rys, rxs = np.where(m_r)
                        if len(rys) > 0:
                            q_bx = (
                                r_box[0] + int(rxs.min()),
                                r_box[1] + int(rys.min()),
                                r_box[0] + int(rxs.max()) + 1,
                                r_box[1] + int(rys.max()) + 1,
                            )
                            q_core = im.crop(q_bx)
                            pad = cfg.padding_px
                            if hint_crop is not None:
                                w_out = max(hint_crop.width, q_core.width) + 2 * pad
                                h_out = hint_crop.height + q_core.height + 3 * pad
                                st = Image.new("RGB", (w_out, h_out), "white")
                                st.paste(hint_crop, (pad, pad))
                                st.paste(q_core, (pad, hint_crop.height + 2 * pad))
                                final_cropped = st
                            else:
                                final_cropped = ImageOps.expand(q_core, border=pad, fill="white")
                            bx = q_bx
                            num_lines = count_text_lines(m_r[rys.min() : rys.max() + 1, rxs.min() : rxs.max() + 1])
                            if num_lines < 3:
                                warnings.append("few_lines")
                            if num_lines <= 2:
                                warnings.append("missing_stem")
                            elif 3 <= num_lines <= 4:
                                warnings.append("options_incomplete")
                            if (q_bx[3] - q_bx[1]) < 80 or num_lines <= 1:
                                warnings.append("missing_options")
                        else:
                            warnings.append("no_text")
                            bx = (0, 0, W, H)
                    else:
                        # Modern 2026 or plain layout
                        masked_im = detect_and_mask_2026_features(im)
                        m_arr = np.array(masked_im)

                        # Use robust text_mask to identify content, ignoring subtle edge artifacts
                        m = text_mask(
                            m_arr,
                            (0, 0, W, H),
                            dark_threshold=cfg.dark_threshold,
                            color_diff_threshold=cfg.color_diff_threshold,
                            border_dark_ratio=cfg.border_dark_ratio,
                            border_edge_depth=cfg.border_edge_depth,
                        )
                        ys, xs = np.where(m)

                        if len(ys) == 0:
                            # Fallback to broader threshold if needed
                            dark = (m_arr[..., 0] < 240) | (m_arr[..., 1] < 240) | (m_arr[..., 2] < 240)
                            ys, xs = np.where(dark)

                        if len(ys) == 0:
                            warnings.append("no_text")
                            bx = (0, 0, W, H)
                            layout = "layout_unknown"
                        else:
                            layout = "modern_2026"
                            bx = (int(xs.min()), int(ys.min()), int(xs.max() + 1), int(ys.max() + 1))
                            # Structural check on detected region
                            num_lines = count_text_lines(m[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1])
                            if num_lines < 3:
                                warnings.append("few_lines")
                            if num_lines <= 2 and not (W == 386 and H == 71):
                                warnings.append("missing_stem")
                            elif 3 <= num_lines <= 4 and not (W == 386 and H == 71):
                                warnings.append("options_incomplete")
                            if (bx[3] - bx[1]) < 80 or num_lines <= 1 or (W == 386 and H == 71):
                                warnings.append("missing_options")

        # Quality Gate Checks on Bounding Box
        if bx[1] <= 2:
            warnings.append("top_edge")
        right_panel_edge = box[2] if box else W
        if (bx[2] >= right_panel_edge - 3 or bx[2] >= W - 3) and layout not in ("fuexam_2026", "cau_n_web_ui", "modern_2026_split_username"):
            warnings.append("right_edge")
        crop_area = (bx[2] - bx[0]) * (bx[3] - bx[1])
        panel_area = (box[2] - box[0]) * (box[3] - box[1]) if box else (W * H)
        is_already_cropped = box is not None and (panel_area >= 0.95 * W * H)
        if crop_area > cfg.crop_too_large_ratio * W * H and not is_already_cropped and layout not in ("fuexam_2026", "cau_n_web_ui", "modern_2026_split_username"):
            warnings.append("crop_too_large")

        # source_clipped check:
        # Only evaluate on red_bar layouts (2024/2025 raw software screenshots)
        if bar:
            # 1. Content loss: ONLY when text touches the border of the ACTUAL SOURCE SCREENSHOT (<= 3px to outer canvas edge)
            canvas_clipped_sides: list = []
            if bx[2] >= W - 3:
                canvas_clipped_sides.append("phải")
            if bx[1] <= 3:
                canvas_clipped_sides.append("trên")
            if bx[3] >= H - 3:
                canvas_clipped_sides.append("dưới")

            # 2. Wide sidebar layout (bar[0] >= 500):
            # Only flag if text genuinely touches and is cut off by the left panel container boundary.
            is_fa24_left_clipped = False
            if layout != "red_bar_left_panel" and bar[0] >= 500 and "no_text" not in warnings and box:
                if bx[0] <= box[0] + 2:
                    p_box = a[box[1]:box[3], box[0]:box[2]].astype(int)
                    m_strict = (p_box.mean(2) < 140) & ((p_box.max(2) - p_box.min(2)) < 60)
                    left_edge_dark = m_strict[:, :2].sum()
                    if left_edge_dark >= 15:
                        is_fa24_left_clipped = True

            if canvas_clipped_sides:
                warnings.append("source_clipped")
                warnings.append("source_clipped_content")
                logger.debug(f"source_clipped (canvas touch) detected on sides: {canvas_clipped_sides}")
            elif is_fa24_left_clipped:
                warnings.append("source_clipped")
                warnings.append("source_clipped_left_only")
                logger.debug("source_clipped_left_only detected (inner exam container clipped A./B./C.)")

        # 5. Crop text and add white margin via canvas expansion (if not already prepared)
        if final_cropped is None:
            cropped_core = im.crop(bx)
            final_cropped = ImageOps.expand(cropped_core, border=cfg.padding_px, fill="white")

        # Hard safety gate: never output a tiny/broken crop (e.g. 139x38 '(Choose 1 answer)' only)
        if (final_cropped.width < 150 or final_cropped.height < 60) and (W >= 300 and H >= 100):
            logger.warning(
                f"Crop too small ({final_cropped.width}x{final_cropped.height}) for {input_path.name}; "
                f"falling back to raw image ({W}x{H})."
            )
            if "crop_too_small_fallback" not in warnings:
                warnings.append("crop_too_small_fallback")
            final_cropped = im
            bx = (0, 0, W, H)

        # Automated check for right-edge text clipping across ALL layouts
        if _detect_right_edge_text_clipping(a, bx, box, final_cropped, cfg, warnings):
            if "text_clipped_right" not in warnings:
                warnings.append("text_clipped_right")

        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if layout == "fuexam_2026":
                palette_im = final_cropped.convert("P", palette=Image.Palette.ADAPTIVE, colors=256)
                palette_im.save(output_path, format="PNG", optimize=True)
            else:
                final_cropped.save(output_path, format="PNG")

        # Note: Separate hint.png image strip is deprecated (v3.0.0);
        # choice hint is preserved directly in the main cropped image.

        return CropResult(
            cropped_image=final_cropped,
            box=bx,
            layout=layout,
            warnings=warnings,
            choice_hint_image=choice_hint_im,
            choice_hint_path=hint_output_path if choice_hint_im else None,
            choice_hint_width_px=choice_hint_w,
            red_bar=bar,
            success="no_text" not in warnings,
            output_path=output_path,
        )


def crop_exam_images(
    exam_id: int,
    exam_title: str,
    questions: list,
    cropped_dir: Path,
    config: Optional[ImageCropConfig] = None,
) -> ExamCropSummary:
    """
    Process all questions of an exam with self-adaptation across questions:
    1. Pass 1: Individual crop.
    2. Pass 2: Calculate dominant layout and median red bar. Retry outliers with median red bar.
    3. Pass 3: Evaluate warning rate (> 20% fallback to raw with prominent notification).
    """
    cfg = config or get_crop_config()
    cropped_dir.mkdir(parents=True, exist_ok=True)

    # Cache invalidation: re-crop if sidecar version differs
    version_file = cropped_dir / ".crop_version"
    cached_version = version_file.read_text().strip() if version_file.exists() else ""
    if cached_version != CROP_ALGORITHM_VERSION:
        for f in cropped_dir.glob("q*.png"):
            f.unlink()
        version_file.write_text(CROP_ALGORITHM_VERSION)

    results: List[CropResult] = []
    red_bars: List[Tuple[int, int]] = []
    layouts_count: Dict[str, int] = {}
    hint_widths: List[int] = []

    # --- Pass 1: Initial Crop ---
    for q in questions:
        if not q.local_image_path:
            # Question has no local image (e.g. comment-only or text-only)
            res = CropResult(
                cropped_image=None,
                box=(0, 0, 0, 0),
                layout="unknown",
                warnings=["no_image"],
                success=False,
            )
            results.append(res)
            continue
        raw_p = Path(q.local_image_path)
        full_raw = raw_p if raw_p.is_absolute() else (get_settings().BASE_DIR / raw_p)
        dst_cropped = cropped_dir / f"q{q.index:03d}.png"
        dst_hint = cropped_dir / f"q{q.index:03d}_hint.png"

        res = crop_question_single(
            input_path=full_raw,
            output_path=dst_cropped,
            hint_output_path=dst_hint,
            config=cfg,
        )
        results.append(res)
        layouts_count[res.layout] = layouts_count.get(res.layout, 0) + 1
        if res.red_bar:
            red_bars.append(res.red_bar)
        if res.choice_hint_width_px:
            hint_widths.append(res.choice_hint_width_px)

    # --- Pass 2: Dominant Layout & Outlier Adaptation ---
    dominant_layout = max(layouts_count.items(), key=lambda x: x[1])[0] if layouts_count else "plain"
    median_red_bar: Optional[Tuple[int, int]] = None

    if "red_bar" in dominant_layout and red_bars:
        med_x0 = int(np.median([b[0] for b in red_bars]))
        med_x1 = int(np.median([b[1] for b in red_bars]))
        median_red_bar = (med_x0, med_x1)

        # Retry questions that failed to detect red bar or had warnings
        for idx, (q, res) in enumerate(zip(questions, results)):
            if res.warnings or res.layout != dominant_layout:
                raw_p = Path(q.local_image_path)
                full_raw = raw_p if raw_p.is_absolute() else (get_settings().BASE_DIR / raw_p)
                dst_cropped = cropped_dir / f"q{q.index:03d}.png"
                dst_hint = cropped_dir / f"q{q.index:03d}_hint.png"

                retry_res = crop_question_single(
                    input_path=full_raw,
                    output_path=dst_cropped,
                    hint_output_path=dst_hint,
                    fallback_red_bar=median_red_bar,
                    config=cfg,
                )
                if len(retry_res.warnings) < len(res.warnings):
                    results[idx] = retry_res

    # Assign crop_warnings to each question object
    for q, res in zip(questions, results):
        q.crop_warnings = res.warnings

    # Log any multiple-choice hint width variation
    if hint_widths and (max(hint_widths) - min(hint_widths)) > 30:
        logger.info(
            f"Đề {exam_title}: phát hiện gợi ý câu hỏi có độ rộng khác nhau rõ rệt ({min(hint_widths)}px .. {max(hint_widths)}px), có thể chứa câu nhiều đáp án."
        )

    # --- Pass 3: Warning Rate Evaluation ---
    total = len(results)
    if dominant_layout in ["red_bar_left_panel", "red_bar+white_panel", "modern_2026", "top_left_white_panel"]:
        critical_warnings = {"no_text", "crop_too_large", "source_clipped_content", "missing_options"}
    else:
        critical_warnings = {"no_text", "few_lines", "crop_too_large", "missing_stem", "missing_options", "source_clipped_content"}
    critical_flagged = [r for r in results if any(w in critical_warnings for w in r.warnings)]
    warning_rate = (len(critical_flagged) / total) if total > 0 else 0.0
    fallback_to_raw = warning_rate > cfg.warning_rate_threshold

    all_flagged = [r for r in results if r.warnings]
    clean_count = total - len(all_flagged)
    if fallback_to_raw:
        logger.warning(
            f"Đề {exam_title}: Kiểu ảnh của đề này chưa được hỗ trợ (>20% cảnh báo: {len(critical_flagged)}/{total}), chuyển sang tạo Word từ ảnh gốc kèm cảnh báo."
        )
        exam_layout = "unsupported_fallback_raw"
    else:
        exam_layout = dominant_layout
        logger.info(f"Đề {exam_title}: kiểu {dominant_layout}, {clean_count}/{total} ảnh sạch.")

    return ExamCropSummary(
        exam_id=exam_id,
        dominant_layout=exam_layout,
        total_questions=total,
        clean_questions=clean_count,
        flagged_questions=len(all_flagged),
        warning_rate=warning_rate,
        fallback_to_raw=fallback_to_raw,
        results=results,
    )


# --- Legacy compatibility function ---
def crop_question_image(
    input_path: Path,
    output_path: Optional[Path] = None,
    margin: int = 12,
    min_width: int = 150,
    min_height: int = 40,
) -> Tuple[Image.Image, bool]:
    """Compatibility wrapper calling modern crop_question_single."""
    res = crop_question_single(input_path, output_path=output_path)
    return res.cropped_image, res.success
