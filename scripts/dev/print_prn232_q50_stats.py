import os
import sys
from pathlib import Path
from collections import Counter
from PIL import Image

# Ensure backend can be imported
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.modules.export.image_cropper import crop_question_single, get_crop_config

def main():
    exam_dir = Path("data/raw/PRN232/exam_194_su25")
    if not exam_dir.exists():
        print(f"Error: {exam_dir} does not exist!")
        return

    files = sorted(list(exam_dir.glob("q*.*")))
    print(f"Directory: {exam_dir}")
    print(f"Total files found: {len(files)}")
    print("-" * 105)
    print(f"{'File':<15} | {'Exists':<6} | {'Bytes':<8} | {'Pillow Open':<11} | {'Dimensions':<12} | {'Layout':<26} | {'Warnings'}")
    print("-" * 105)

    cfg = get_crop_config()
    warning_counter = Counter()
    layout_counter = Counter()

    for f in files:
        f_exists = f.exists()
        f_size = f.stat().st_size if f_exists else 0
        pillow_ok = False
        fmt = "-"
        dims_str = "-"
        try:
            with Image.open(f) as im:
                pillow_ok = True
                fmt = im.format
                dims_str = f"{im.width}x{im.height}"
        except Exception as e:
            pillow_ok = False
            dims_str = str(e)

        try:
            res = crop_question_single(f, config=cfg)
            layout_str = res.layout
            warns = res.warnings
        except Exception as e:
            layout_str = f"ERROR: {type(e).__name__}"
            warns = ["exception"]

        layout_counter[layout_str] += 1
        for w in warns:
            warning_counter[w] += 1

        warn_str = ", ".join(warns) if warns else "clean"
        print(f"{f.name:<15} | {str(f_exists):<6} | {f_size:<8} | {str(pillow_ok):<11} | {dims_str:<12} | {layout_str:<26} | {warn_str}")

    print("-" * 105)
    print("\nSummary:")
    print(f"Total questions: {len(files)}")
    print("Layout distribution:")
    for l, c in layout_counter.items():
        print(f"  - {l}: {c}")
    print("Warning counts by type:")
    for w, c in warning_counter.items():
        print(f"  - {w}: {c}")

if __name__ == "__main__":
    main()
