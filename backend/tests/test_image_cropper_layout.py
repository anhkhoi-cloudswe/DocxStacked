from pathlib import Path
import pytest
import numpy as np
from PIL import Image

from backend.app.modules.export.image_cropper import (
    crop_question_single,
    find_red_bar,
    white_panel,
    text_mask,
    extract_choice_hint,
    get_crop_config,
    CropResult,
)
from backend.app.modules.crawler.browser import SessionManager, get_browser_manager


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "crop"


def test_crop_fixtures_all_three_years(tmp_path: Path):
    """
    Verify 9 real fixtures (3 each of 2024, 2025, 2026):
    - Layout recognized correctly.
    - Zero warning flags.
    - Text does not touch edges (top_edge, right_edge).
    - Height >= 100px.
    - No red bar pixels remaining in cropped image.
    - No solid yellow clock or blue header blocks.
    - Cropped image is < 60% of original image area.
    """
    assert FIXTURES_DIR.exists()
    fixtures = [
        ("2024_q01_short.webp", "red_bar"),
        ("2024_q10_long.webp", "red_bar"),
        ("2024_q53_xml.webp", "red_bar"),
        ("2025_q01_short.webp", "red_bar"),
        ("2025_q13_long.webp", "red_bar"),
        ("2025_q36_code.webp", "red_bar"),
        ("2026_q01_short.jpg", "modern_2026"),
        ("2026_q19_code.jpg", "modern_2026"),
        ("2026_q36_long.jpg", "modern_2026"),
    ]

    for fname, expected_layout_prefix in fixtures:
        src = FIXTURES_DIR / fname
        assert src.exists(), f"Missing fixture file: {src}"

        out_cropped = tmp_path / f"out_{fname}.png"
        out_hint = tmp_path / f"hint_{fname}.png"

        res: CropResult = crop_question_single(
            input_path=src,
            output_path=out_cropped,
            hint_output_path=out_hint,
        )

        # 1. Layout recognized
        assert expected_layout_prefix in res.layout, f"{fname}: expected {expected_layout_prefix} in {res.layout}"

        # 2. Zero warning flags
        assert res.warnings == [], f"{fname} had warnings: {res.warnings}"

        # 3. Height >= 100px
        assert res.cropped_image.height >= 100, f"{fname} height too small: {res.cropped_image.height}"

        # 4. Cropped area < 60% of original
        with Image.open(src) as orig_im:
            orig_area = orig_im.width * orig_im.height
            cropped_area = res.cropped_image.width * res.cropped_image.height
            area_ratio = cropped_area / orig_area
            assert area_ratio < 0.60, f"{fname} cropped area ratio too large: {area_ratio:.3f}"

        # 5. No red bar pixels in cropped image
        arr = np.array(res.cropped_image)
        r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
        red_pixels = (r > 170) & (g < 80) & (b < 80)
        assert int(red_pixels.sum()) == 0, f"{fname} contains red bar pixels in crop: {red_pixels.sum()}"

        # 6. No solid yellow pixels (clock in 2024: R>200, G>200, B<50)
        yellow_pixels = (r > 200) & (g > 200) & (b < 50)
        assert int(yellow_pixels.sum()) == 0, f"{fname} contains clock yellow pixels in crop: {yellow_pixels.sum()}"

        # 7. No solid blue pixels (2026 title bar: B>160, R<100, G<140)
        blue_pixels = (b > 160) & (r < 100) & (g < 140)
        assert int(blue_pixels.sum()) == 0, f"{fname} contains blue header pixels in crop: {blue_pixels.sum()}"


def test_sensor_blank_and_gray_images(tmp_path: Path):
    """
    Sensor test: pure white and pure gray images must produce 'no_text' warning
    and NOT crash or throw unhandled exceptions.
    """
    # 1. Pure white
    white_img = Image.new("RGB", (800, 600), color=(255, 255, 255))
    white_p = tmp_path / "white.png"
    white_img.save(white_p)

    res_white = crop_question_single(white_p)
    assert not res_white.success
    assert "no_text" in res_white.warnings

    # 2. Pure gray
    gray_img = Image.new("RGB", (800, 600), color=(128, 128, 128))
    gray_p = tmp_path / "gray.png"
    gray_img.save(gray_p)

    res_gray = crop_question_single(gray_p)
    assert not res_gray.success
    assert "no_text" in res_gray.warnings


def test_choice_hint_extraction():
    """Verify choice hint extraction on 2024 and 2025 images with red bars."""
    src_2024 = FIXTURES_DIR / "2024_q01_short.webp"
    src_2025 = FIXTURES_DIR / "2025_q01_short.webp"

    res24 = crop_question_single(src_2024)
    assert res24.choice_hint_image is not None
    assert res24.choice_hint_width_px is not None
    assert res24.choice_hint_width_px > 30

    res25 = crop_question_single(src_2025)
    assert res25.choice_hint_image is not None
    assert res25.choice_hint_width_px is not None
    assert res25.choice_hint_width_px > 60


def test_all_60_questions_prm392_sp24():
    """
    Run layout crop on all 60 real raw images of PRM392 - SP 2024.
    With white_panel edge checking (<= 3px to panel boundary), exactly 2 questions
    touch the source window border (q45 and q57) and are properly flagged with 'right_edge'.
    58 questions are completely clean.
    """
    exam_dir = Path("data/raw/PRM392/exam_41_SP24")
    if not exam_dir.exists():
        pytest.skip("data/raw/PRM392/exam_41_SP24 not present in environment")

    files = sorted(exam_dir.glob("*.webp"))
    assert len(files) == 60, f"Expected 60 questions, found {len(files)}"

    clean_count = 0
    flagged = []
    for f in files:
        res = crop_question_single(f)
        if not res.warnings:
            clean_count += 1
        else:
            flagged.append((f.name, res.warnings))

    # With header divider filtering (y_start >= 49), top progress bar text is properly excluded,
    # and all 60 questions in PRM392 SP24 are cleanly cropped without spurious right_edge flags.
    assert clean_count == 60, f"Expected 60 clean, got {clean_count}. Flagged: {flagged}"
    assert len(flagged) == 0


def test_session_manager_invalidation():
    """Verify SessionManager invalidation closes any active context."""
    bm = get_browser_manager()
    SessionManager.invalidate()
    assert bm._context is None
    assert bm._playwright is None


def test_closing_punctuation_preserved_q02_sp24(tmp_path: Path):
    """
    Verify that closing quotation marks, dots, and punctuation at line end
    are NOT removed by speckle filtering.
    In Question 2 of SP24, Option B ends with '"black-boxes"'.
    Previous speckle filter (< 6px) removed the closing quote, stopping at x=1275.
    With speckle removal removed, bounding box reaches x=1283, fully preserving the quote.
    """
    fixture = FIXTURES_DIR / "2024_q02_closing_quote.webp"
    assert fixture.exists(), f"Fixture missing: {fixture}"
    out_p = tmp_path / "q02_cropped.png"
    res = crop_question_single(fixture, output_path=out_p)

    # Check that x_max reaches at least 1283 (closing quote)
    assert res.box[2] >= 1282, f"Closing quote cut off: box right edge is {res.box[2]} (expected >= 1282)"

    # Check that text is padded by >= 12px canvas padding on all sides
    cropped_im = res.cropped_image
    arr = np.array(cropped_im)
    dark_cols = np.where((arr < 240).any(axis=2).any(axis=0))[0]
    assert len(dark_cols) > 0
    rightmost_pixel_col = dark_cols.max()
    right_margin = cropped_im.width - 1 - rightmost_pixel_col
    assert right_margin >= 12, f"Right margin too small: {right_margin}px (expected >= 12px)"
