import numpy as np
from PIL import Image
from pathlib import Path
import sys
sys.path.insert(0, str(Path.cwd()))

from backend.app.modules.export.image_cropper import text_mask, ImageCropConfig, count_text_lines

def test_full_exam_194():
    raw_dir = Path("data/raw/PRN232/exam_194_su25")
    files = sorted(raw_dir.glob("*.webp"))
    cfg = ImageCropConfig()
    
    print(f"Testing {len(files)} questions with new left panel box:")
    all_boxes = []
    under_80 = []
    clipped_left = []
    
    for idx, f in enumerate(files, start=1):
        im = Image.open(f).convert("RGB")
        arr = np.array(im)
        H, W, _ = arr.shape
        
        # New Kizspy left panel ROI
        # Bar is around 809..811
        box = (15, 90, 805, min(H, 695))
        m = text_mask(
            arr,
            box,
            dark_threshold=cfg.dark_threshold,
            color_diff_threshold=cfg.color_diff_threshold,
            allow_subpixel=True,
            border_dark_ratio=cfg.border_dark_ratio,
            border_edge_depth=cfg.border_edge_depth,
        )
        ys, xs = np.where(m)
        if len(ys) == 0:
            print(f"Q{idx}: NO TEXT!")
            continue
        bx = (
            int(box[0] + xs.min()),
            int(box[1] + ys.min()),
            int(box[0] + xs.max() + 1),
            int(box[1] + ys.max() + 1),
        )
        w = bx[2] - bx[0]
        h = bx[3] - bx[1]
        all_boxes.append((idx, bx, w, h))
        if h < 80:
            under_80.append((idx, f.name, w, h))
        if bx[0] <= 18:
            clipped_left.append((idx, bx[0]))
            
    print(f"Total processed: {len(all_boxes)}")
    print(f"Questions with height < 80px: {len(under_80)}")
    print(f"Questions touching left margin (<= 18px): {len(clipped_left)}")
    
    # Print sample
    for idx in [1, 2, 3, 8, 31, 34, 36, 45, 48, 49]:
        item = all_boxes[idx - 1]
        print(f"Q{item[0]:02d}: box={item[1]}, size={item[2]}x{item[3]}")

if __name__ == "__main__":
    test_full_exam_194()
