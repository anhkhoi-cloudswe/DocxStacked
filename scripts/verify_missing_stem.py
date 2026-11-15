"""
Verify extracted Word images: count groups, check for missing_stem.
Run after extract_docx_images.py.
Usage: .\.venv\Scripts\python.exe scripts/verify_missing_stem.py <images_dir>
"""
import sys
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0, str(Path(__file__).parent.parent))
from backend.app.modules.export.image_cropper import count_text_lines


def verify(images_dir: str):
    d = Path(images_dir)
    images = sorted(d.glob("q*.png"))
    print(f"Directory: {d}")
    print(f"Images found: {len(images)}")
    print()

    missing_stem = []
    for img_path in images:
        im = Image.open(img_path).convert("RGB")
        a = np.array(im)
        dark = a.mean(2) < 200
        n = count_text_lines(dark)
        w, h = im.size
        if 2 <= n <= 4:
            missing_stem.append((img_path.name, w, h, n))
            flag = "  ← MISSING_STEM"
        else:
            flag = ""
        print(f"  {img_path.name}: {w}x{h}, lines={n}{flag}")

    print()
    print(f"missing_stem count: {len(missing_stem)}  (must be 0)")
    if missing_stem:
        for name, w, h, n in missing_stem:
            print(f"  {name}: {w}x{h}, lines={n}")
    else:
        print("  ✅ All images have full question stems")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/verify_missing_stem.py <images_dir>")
        sys.exit(1)
    verify(sys.argv[1])
