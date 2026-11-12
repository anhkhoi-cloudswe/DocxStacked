import io
from pathlib import Path
from typing import Optional, Tuple
from PIL import Image, ImageDraw

from backend.app.core.logging import get_logger

logger = get_logger(__name__)


def crop_question_image(
    input_path: Path,
    output_path: Optional[Path] = None,
    margin: int = 12,
    min_width: int = 150,
    min_height: int = 40,
) -> Tuple[Image.Image, bool]:
    """
    Crop exam question image to keep only question text, diagrams, and options A-D.
    - Masks the top 'MULTIPLE CHOICE' title bar with white (y: 0..36).
    - Masks the bottom-left FUOVERFLOW watermark with white (x: 0..180, y: 630..h).
    - Masks edge 2px border.
    - Finds content bounding box and adds margin.
    - Fallbacks to original image if cropped area is unusually small (<150px wide or <40px high).
    """
    if not input_path.exists():
        raise FileNotFoundError(f"Image file not found: {input_path}")

    with Image.open(input_path) as raw_im:
        im = raw_im.convert("RGB")
        w, h = im.size

        # Create working mask copy to locate content bounding box
        masked = im.copy()
        draw = ImageDraw.Draw(masked)

        # 1. Che thanh tieu de tren (thanh xanh + chu MULTIPLE CHOICE)
        if h > 50:
            draw.rectangle([0, 0, w, min(36, h)], fill=(255, 255, 255))

        # 2. Che watermark logo FUOVERFLOW goc duoi trai
        if h > 630:
            draw.rectangle([0, 630, min(180, w), h], fill=(255, 255, 255))

        # 3. Che 2px vien mep ngoai de loai bo artifact nen
        draw.rectangle([0, 0, 2, h], fill=(255, 255, 255))
        draw.rectangle([w - 2, 0, w, h], fill=(255, 255, 255))
        draw.rectangle([0, h - 2, w, h], fill=(255, 255, 255))

        pixels = masked.load()
        min_x, min_y, max_x, max_y = w, h, 0, 0
        found = False

        for y in range(h):
            for x in range(w):
                r, g, b = pixels[x, y]
                # Non-white pixel threshold
                if r < 240 or g < 240 or b < 240:
                    found = True
                    if x < min_x:
                        min_x = x
                    if x > max_x:
                        max_x = x
                    if y < min_y:
                        min_y = y
                    if y > max_y:
                        max_y = y

        if not found:
            logger.warning(f"No content found in {input_path.name}, using original image.")
            if output_path:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                im.save(output_path, format="PNG")
            return im, False

        crop_w = max_x - min_x
        crop_h = max_y - min_y

        if crop_w < min_width or crop_h < min_height:
            logger.warning(
                f"Cropped area unusually small for {input_path.name} ({crop_w}x{crop_h} < {min_width}x{min_height}), fallback to original."
            )
            if output_path:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                im.save(output_path, format="PNG")
            return im, False

        # Add 12px margin
        x1 = max(0, min_x - margin)
        y1 = max(0, min_y - margin)
        x2 = min(w, max_x + margin)
        y2 = min(h, max_y + margin)

        cropped = im.crop((x1, y1, x2, y2))

        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            cropped.save(output_path, format="PNG")

        return cropped, True

