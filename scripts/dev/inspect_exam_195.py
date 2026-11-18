import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))

from backend.app.modules.export.image_cropper import crop_question_single, ImageCropConfig

def inspect_exam_195():
    raw_dir = Path("data/raw/PRN232/exam_195_su26")
    files = sorted(raw_dir.glob("*.webp"))
    print(f"Total files in exam_195: {len(files)}")
    
    cfg = ImageCropConfig()
    
    flagged = []
    layouts = {}
    for idx, f in enumerate(files, start=1):
        res = crop_question_single(f, config=cfg)
        layouts[res.layout] = layouts.get(res.layout, 0) + 1
        bx = res.box
        h = bx[3] - bx[1]
        w = bx[2] - bx[0]
        if res.warnings or idx in [1, 20, 21, 25, 50]:
            print(f"Q{idx:02d} ({f.name}): layout={res.layout}, box={bx} ({w}x{h}), warnings={res.warnings}")
        if res.warnings:
            flagged.append((idx, f.name, res.layout, res.warnings, w, h))

    print(f"\nLayouts summary: {layouts}")
    print(f"Total flagged questions: {len(flagged)}/{len(files)}")

if __name__ == "__main__":
    inspect_exam_195()
