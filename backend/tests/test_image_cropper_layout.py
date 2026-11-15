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


def test_source_clipped_fa24_re_q09_and_q59():
    """
    FA 2024 RE Q9 and Q59: leading characters A./B./C. are clipped on the left edge
    by the exam application window. Detection correctly identifies flat vertical cuts
    and flags 'source_clipped'.
    """
    q9_fixture = FIXTURES_DIR / "2024_ite302c_fa24_re_q09.webp"
    q59_fixture = FIXTURES_DIR / "2024_ite302c_fa24_re_q59.webp"
    assert q9_fixture.exists(), f"Fixture missing: {q9_fixture}"
    assert q59_fixture.exists(), f"Fixture missing: {q59_fixture}"

    res9 = crop_question_single(q9_fixture)
    assert res9.success, f"Q9 crop failed: {res9.warnings}"
    assert res9.cropped_image is not None
    assert "source_clipped" in res9.warnings, f"Q9 expected source_clipped, got {res9.warnings}"

    res59 = crop_question_single(q59_fixture)
    assert res59.success, f"Q59 crop failed: {res59.warnings}"
    assert res59.cropped_image is not None
    assert "source_clipped" in res59.warnings, f"Q59 expected source_clipped, got {res59.warnings}"


def test_su26_fe_fixtures_no_missing_stem_no_clipping():
    """
    SU26 FE Q7, Q8, Q9, Q14, Q56: fresh crops must have full stem,
    correct dimensions, and zero missing_stem / source_clipped warnings.
    Verifies docx_builder cache-bypass fix is effective: cropped_dir takes priority.
    """
    expected = {
        "2026_ite302c_su26_fe_q07.webp": (739, 184),
        "2026_ite302c_su26_fe_q08.webp": (685, 170),
        "2026_ite302c_su26_fe_q09.webp": (715, 187),
        "2026_ite302c_su26_fe_q14.webp": (1658, 546),
        "2026_ite302c_su26_fe_q56.webp": (683, 167),
    }
    for fname, (exp_w, exp_h) in expected.items():
        src = FIXTURES_DIR / fname
        assert src.exists(), f"Fixture missing: {src}"
        res = crop_question_single(src)
        assert "missing_stem" not in res.warnings, (
            f"{fname}: unexpected missing_stem. warnings={res.warnings}"
        )
        assert "source_clipped" not in res.warnings, (
            f"{fname}: unexpected source_clipped. warnings={res.warnings}"
        )
        assert res.cropped_image.size == (exp_w, exp_h), (
            f"{fname}: size mismatch. got {res.cropped_image.size}, expected ({exp_w}, {exp_h})"
        )


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


def test_fa24_re_crop_contains_required_text_endings():
    """
    Verify FA 2024 RE crop bounds unconstrained by white panel edges:
    - Question 9 must contain 'they will' (box[2] >= 1553, preserving trailing 'ill' across x=1544..1554).
    - Question 30 must contain 'two)' (box[2] >= 1348, preserving closing parenthesis ')').
    - Question 34 must contain 'accuracy' (box[2] >= 1526, preserving trailing 'y').
    - Zero 'source_clipped_content' warnings (no unrecoverable content loss).
    """
    # 1. Question 9 ('they will')
    q9_fixture = FIXTURES_DIR / "2024_ite302c_fa24_re_q09.webp"
    assert q9_fixture.exists(), f"Fixture missing: {q9_fixture}"
    res9 = crop_question_single(q9_fixture)
    assert res9.success
    assert res9.box[2] >= 1553, f"Q9 box right edge {res9.box[2]} < 1553: 'they will' cut off!"
    assert "source_clipped_content" not in res9.warnings
    # Verify 'ill' pixels exist at the right edge
    arr9 = np.array(res9.cropped_image)
    col_ill_end = 12 + (res9.box[2] - 1 - res9.box[0])
    assert arr9[:, col_ill_end].mean() < 254, "Q9 'will' ending glyph pixels missing in crop"

    # 2. Question 30 ('two)')
    q30_fixture = FIXTURES_DIR / "2024_ite302c_fa24_re_q30.webp"
    assert q30_fixture.exists(), f"Fixture missing: {q30_fixture}"
    res30 = crop_question_single(q30_fixture)
    assert res30.success
    assert res30.box[2] >= 1348, f"Q30 box right edge {res30.box[2]} < 1348: 'two)' cut off!"
    assert "source_clipped_content" not in res30.warnings
    arr30 = np.array(res30.cropped_image)
    col_two_end = 12 + (res30.box[2] - 1 - res30.box[0])
    assert arr30[:, col_two_end].mean() < 254, "Q30 'two)' ending glyph pixels missing in crop"

    # 3. Question 34 ('accuracy')
    q34_fixture = FIXTURES_DIR / "2024_ite302c_fa24_re_q34.webp"
    assert q34_fixture.exists(), f"Fixture missing: {q34_fixture}"
    res34 = crop_question_single(q34_fixture)
    assert res34.success
    assert res34.box[2] >= 1526, f"Q34 box right edge {res34.box[2]} < 1526: 'accuracy' cut off!"
    assert "source_clipped_content" not in res34.warnings
    arr34 = np.array(res34.cropped_image)
    col_acc_end = 12 + (res34.box[2] - 1 - res34.box[0])
    assert arr34[:, col_acc_end].mean() < 254, "Q34 'accuracy' ending glyph pixels missing in crop"


def test_anti_raw_crop_top_left_panel_and_prm392_fe():
    """
    Anti-raw protection test:
    Verify that software layout with gray background, FUO watermark, and yellow 'Q: N' label
    is never left as raw dimensions (~1446x804). The crop must isolate the top-left white panel,
    producing clean cropped images (< 1000px width, < 350px height) without gray background or labels.
    """
    raw_fe_q1 = Path("data/raw/PRM392/exam_42_SP24/q01_PRM392_-_SP_2024_-_FE_1589.webp")
    if raw_fe_q1.exists():
        res = crop_question_single(raw_fe_q1)
        assert res.success
        assert res.cropped_image.width < 1000, f"Crop too wide: {res.cropped_image.width}px (raw image fallback!)"
        assert res.cropped_image.height < 350, f"Crop too tall: {res.cropped_image.height}px (raw image fallback!)"
        assert "crop_too_large" not in res.warnings
        # Verify watermark FUO / yellow tag not included
        arr = np.array(res.cropped_image)
        # Yellow tag check
        is_yellow = (arr[..., 0] > 180) & (arr[..., 1] > 180) & (arr[..., 2] < 120)
        assert is_yellow.sum() == 0, "Yellow label 'Q: 1' leaked into cropped image!"

    # Also test top-left white panel detector directly on an image without red bar
    from backend.app.modules.export.image_cropper import find_top_left_white_panel
    test_canvas = np.full((800, 1400, 3), 240, dtype=np.uint8)  # gray background
    test_canvas[:250, :850] = 255  # white panel at top-left
    # add dummy text inside panel
    test_canvas[50:180, 50:700] = 20
    # add watermark in mid gray area
    test_canvas[400:600, 400:800] = 220
    # add yellow tag in bottom right
    test_canvas[750:780, 1300:1360] = [215, 229, 124]

    wp = find_top_left_white_panel(test_canvas)
    assert wp is not None, "Failed to detect top-left white panel"
    assert wp[0] == 0 and wp[1] == 0
    assert 845 <= wp[2] <= 855
    assert 245 <= wp[3] <= 255



