import numpy as np
from PIL import Image

def analyze_full_q8():
    im = Image.open("data/raw/PRN232/exam_194_su25/q08_Q8.webp").convert("RGB")
    arr = np.array(im)
    w, h = im.size
    print("Full Q8 size:", w, h)
    
    # Check dark pixels across entire image:
    dark = (arr.mean(2) < 180) & ((arr.max(2) - arr.min(2)) < 60)
    
    # Let's check columns with dark pixels
    col_sums = dark.sum(axis=0)
    print("Non-empty column ranges:")
    ranges = []
    start = None
    for x in range(w):
        if col_sums[x] > 10:
            if start is None: start = x
        else:
            if start is not None:
                ranges.append((start, x-1, col_sums[start:x].sum()))
                start = None
    if start is not None:
        ranges.append((start, w-1, col_sums[start:].sum()))
    for r in ranges:
        print(f"  x=[{r[0]}..{r[1]}], total_dark={r[2]}")

    # Check rows with dark pixels
    row_sums = dark.sum(axis=1)
    print("\nNon-empty row ranges:")
    ranges = []
    start = None
    for y in range(h):
        if row_sums[y] > 10:
            if start is None: start = y
        else:
            if start is not None:
                ranges.append((start, y-1, row_sums[start:y].sum()))
                start = None
    if start is not None:
        ranges.append((start, h-1, row_sums[start:].sum()))
    for r in ranges:
        print(f"  y=[{r[0]}..{r[1]}], total_dark={r[2]}")

if __name__ == "__main__":
    analyze_full_q8()
