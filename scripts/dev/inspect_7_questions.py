import numpy as np
from PIL import Image
from pathlib import Path

def inspect_7_questions():
    raw_dir = Path("data/raw/PRN232/exam_194_su25")
    q_indices = [8, 31, 34, 36, 45, 48, 49]
    for q in q_indices:
        files = list(raw_dir.glob(f"q{q:02d}_*.webp"))
        if not files: files = list(raw_dir.glob(f"q{q:03d}_*.webp"))
        raw_file = files[0]
        im = Image.open(raw_file).convert("RGB")
        arr = np.array(im)
        
        # Check text in 160..810
        mid = arr[:, 160:810]
        dark = (mid.mean(2) < 170) & ((mid.max(2) - mid.min(2)) < 50)
        ys, xs = np.where(dark)
        if len(ys) > 0:
            print(f"Q{q:02d} ({raw_file.name}): ys=[{ys.min()}..{ys.max()}], height={ys.max()-ys.min()+1}, xs=[{xs.min()+160}..{xs.max()+160}], dark_px={len(ys)}")
            # Let's save a crop of this question area
            im.crop((120, max(0, ys.min()-20), 810, min(780, ys.max()+50))).save(f"data/inspect_prn232/q{q:02d}_crop_candidate.png")
        else:
            print(f"Q{q:02d}: NO text in mid area!")

if __name__ == "__main__":
    inspect_7_questions()
