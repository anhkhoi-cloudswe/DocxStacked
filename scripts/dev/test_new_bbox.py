import numpy as np
from PIL import Image
from pathlib import Path

def test_new_bbox():
    raw_dir = Path("data/raw/PRN232/exam_194_su25")
    all_files = sorted(raw_dir.glob("*.webp"))
    print(f"Total files: {len(all_files)}")
    
    under_60_px = []
    heights = []

    for idx, f in enumerate(all_files, start=1):
        im = Image.open(f).convert("RGB")
        arr = np.array(im)
        H, W, _ = arr.shape
        
        # Region of interest for Kizspy left panel question:
        # x: 15 to 805
        # y: 92 to 695 (below "Choose 1 answer" and above bottom footer)
        roi = arr[92:695, 15:805]
        dark = (roi.mean(2) < 170) & ((roi.max(2) - roi.min(2)) < 50)
        
        ys, xs = np.where(dark)
        if len(ys) == 0:
            print(f"Q{idx} ({f.name}): NO TEXT!")
            continue
            
        x0 = 15 + xs.min()
        y0 = 92 + ys.min()
        x1 = 15 + xs.max() + 1
        y1 = 92 + ys.max() + 1
        
        h = y1 - y0
        w = x1 - x0
        heights.append(h)
        if h < 60:
            under_60_px.append((idx, f.name, w, h, (x0, y0, x1, y1)))
        
        if idx in [1, 2, 3, 8, 31, 34, 36, 45, 48, 49]:
            print(f"Q{idx:02d} ({f.name}): box=({x0}, {y0}, {x1}, {y1}), size={w}x{h}")

    print(f"\nSummary across {len(all_files)} questions:")
    print(f"Min height: {min(heights)}, Max height: {max(heights)}, Median height: {np.median(heights)}")
    print(f"Questions with height < 60px: {len(under_60_px)}")
    if under_60_px:
        for item in under_60_px:
            print(f"   {item}")

if __name__ == "__main__":
    test_new_bbox()
