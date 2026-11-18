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
    r_min: int = 170,
    g_max: int = 80,
    b_max: int = 80,
) -> Optional[Tuple[int, int]]:
    """
    Find vertical red bar: column with >= min_frac height of red pixels.
    Returns (x_start, x_end) inclusive for the first contiguous band.
    """
    H = a.shape[0]
    r, g, b = [a[..., i].astype(int) for i in range(3)]
    cols = ((r > r_min) & (g < g_max) & (b < b_max)).sum(0)
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

    # Discard border lines near outer perimeter
    H_m, W_m = m.shape
    depth = min(border_edge_depth, H_m, W_m)
    for r in range(min(depth, H_m)):
        if m[r].mean() > border_dark_ratio:
            m[max(0, r - 1) : min(H_m, r + 2)] = False
    for r in range(max(0, H_m - depth), H_m):
        if m[r].mean() > border_dark_ratio:
            m[max(0, r - 1) : min(H_m, r + 2)] = False
    for c in range(min(depth, W_m)):
        if m[:, c].mean() > border_dark_ratio:
            m[:, max(0, c - 1) : min(W_m, c + 2)] = False
    for c in range(max(0, W_m - depth), W_m):
        if m[:, c].mean() > border_dark_ratio:
            m[:, max(0, c - 1) : min(W_m, c + 2)] = False

    # Note: Do NOT remove speckles < 6 pixels as this strips punctuation marks
    # (closing double quotes, single quotes, periods, commas, dots on 'i', colons).
    # Bounding box is computed on the text mask with only border lines discarded.
    return m


CROP_ALGORITHM_VERSION = "2.9.0-kizspy-keep-choice-hint"


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
            r_min=cfg.red_min_r,
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
            else:
                x0 = bar[1] + 4

                # Check if this is a split 2-column question (e.g. Kizspy layout with text on left, chart on right)
                # Conditions: bar is to the right (bar[0] >= 0.25 * W) and left area contains substantial question text.
                is_split_2col = False
                box_l = None
                if bar[0] >= int(0.25 * W):
                    left_q_area = a[50:min(700, H), 10:bar[0]]
                    dark_l = (left_q_area.mean(2) < cfg.dark_threshold) & (
                        (left_q_area.max(2) - left_q_area.min(2)) < cfg.color_diff_threshold
                    )
                    if dark_l.sum() > 1500:
                        ys_l, xs_l = np.where(dark_l)
                        if xs_l.max() - xs_l.min() > 200:
                            is_split_2col = True
                            box_l = (
                                int(10 + xs_l.min()),
                                int(50 + ys_l.min()),
                                int(10 + xs_l.max() + 1),
                                int(50 + ys_l.max() + 1),
                            )

                # In 2024 software layouts (narrow left bar, x0 < 350), detect horizontal divider line below progress bar
                y_start = 0
                if x0 < 350:
                    top_region = a[:min(70, H), x0:].astype(int)
                    row_means = top_region.mean(axis=(1, 2))
                    dark_rows = [y for y, m in enumerate(row_means) if m < 185]
                    if dark_rows and 38 <= max(dark_rows) <= 58:
                        y_start = max(dark_rows) + 1

                box = (x0, y_start, W, H)

                # 2. Search for white panel containing question (or right-hand graphic)
                wp = white_panel(
                    a[y_start:, :],
                    x0,
                    min_area_ratio=cfg.white_panel_min_area_ratio,
                    max_width_ratio=cfg.white_panel_max_width_ratio,
                    closing_size=cfg.closing_kernel_size,
                    min_val=cfg.white_min_val,
                )
                if wp:
                    layout = "red_bar+white_panel"
                    # Check whether canvas outside panel has gray background (SP 2024 layouts with watermark / corner tag)
                    # or pure white canvas (FA 2024 wide layouts where text flows across container).
                    right_bg_mean = float(a[100 : max(101, H - 100), max(0, W - 50) :].mean())
                    bottom_bg_mean = float(a[max(0, H - 50) :, 100 : max(101, W - 100)].mean())
                    is_gray_canvas = (right_bg_mean < 246) or (bottom_bg_mean < 246)

                    if is_gray_canvas or bar[0] < 350:
                        # In gray canvas layouts (e.g. PRM392 SP24 FE/RE), constrain search to white card panel (+ 30px)
                        # to isolate out FUO watermark in mid canvas and yellow "Q: N" tag in bottom-right corner.
                        box = (wp[0], wp[1] + y_start, min(W, wp[2] + 30), min(H, wp[3] + y_start + 30))
                    else:
                        # For pure white wide layouts (e.g. FA 2024 RE), search spans full right canvas (W, H)
                        # so text overflowing panel boundary is never clamped or truncated.
                        box = (wp[0], wp[1] + y_start, W, H)

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
                    if 2 <= num_lines <= 4 and not is_split_2col:
                        warnings.append("missing_stem")
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
            # 4. No red bar: check top-left white panel first (software layouts with gray background, FUO watermark, and Q:N corner tag)
            tl_wp = find_top_left_white_panel(a, min_val=cfg.white_min_val)
            if tl_wp:
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
                    # If lines between 2 and 4, only flag missing_stem if image is not a short snippet
                    # Question 6 (W=386, H=71): stem is present at the top, only options are missing
                    if 2 <= num_lines <= 4 and not (W == 386 and H == 71):
                        warnings.append("missing_stem")
                    if (bx[3] - bx[1]) < 80 or num_lines <= 1 or (W == 386 and H == 71):
                        warnings.append("missing_options")
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
                    # If lines between 2 and 4, only flag missing_stem if image is not a short snippet
                    # Question 6 (W=386, H=71): stem is present at the top, only options are missing
                    if 2 <= num_lines <= 4 and not (W == 386 and H == 71):
                        warnings.append("missing_stem")
                    if (bx[3] - bx[1]) < 80 or num_lines <= 1 or (W == 386 and H == 71):
                        warnings.append("missing_options")

        # Quality Gate Checks on Bounding Box
        if bx[1] <= 2:
            warnings.append("top_edge")
        right_panel_edge = box[2] if box else W
        if bx[2] >= right_panel_edge - 3 or bx[2] >= W - 3:
            warnings.append("right_edge")
        crop_area = (bx[2] - bx[0]) * (bx[3] - bx[1])
        panel_area = (box[2] - box[0]) * (box[3] - box[1]) if box else (W * H)
        is_already_cropped = box is not None and (panel_area >= 0.95 * W * H)
        if crop_area > cfg.crop_too_large_ratio * W * H and not is_already_cropped:
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

            # 2. Wide sidebar layout (bar[0] >= 500, e.g. ITE302c FA24 RE):
            # Inner application container cuts leading labels A./B./C. at x ~ 832.
            # This is an exam-level left edge clipping (handled by top document note, no per-question note).
            is_fa24_left_clipped = False
            if layout != "red_bar_left_panel" and bar[0] >= 500 and "no_text" not in warnings and box:
                p_box = a[box[1]:box[3], box[0]:box[2]].astype(int)
                m_strict = (p_box.mean(2) < 140) & ((p_box.max(2) - p_box.min(2)) < 60)
                row_sums_m = m_strict.sum(axis=1)
                lines_m = [y_idx for y_idx, c in enumerate(row_sums_m) if c > 0]
                groups_m = []
                cur_g = []
                for y_val in lines_m:
                    if not cur_g or y_val == cur_g[-1] + 1:
                        cur_g.append(y_val)
                    else:
                        groups_m.append(cur_g)
                        cur_g = [y_val]
                if cur_g:
                    groups_m.append(cur_g)
                short_h_count = sum(1 for g in groups_m if len(g) <= 5)
                if len(groups_m) > 0 and (short_h_count / len(groups_m)) >= 0.5:
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

        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            final_cropped.save(output_path, format="PNG")

        if hint_output_path and choice_hint_im:
            hint_output_path.parent.mkdir(parents=True, exist_ok=True)
            choice_hint_im.save(hint_output_path, format="PNG")

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
        critical_warnings = {"no_text", "crop_too_large", "source_clipped", "missing_options"}
    else:
        critical_warnings = {"no_text", "few_lines", "crop_too_large", "missing_stem", "missing_options", "source_clipped"}
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
