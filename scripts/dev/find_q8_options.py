from PIL import Image
import numpy as np

def find_q8_options():
    im = Image.open("data/raw/PRN232/exam_194_su25/q08_Q8.webp").convert("RGB")
    arr = np.array(im)
    w, h = im.size
    print("Finding options across full width for Q8...")
    dark = (arr.mean(2) < 170) & ((arr.max(2) - arr.min(2)) < 50)
    
    # Check all rows from 120 to 750
    for y in range(120, 750, 10):
        row_dark = dark[y:y+10, :]
        ys, xs = np.where(row_dark)
        if len(xs) > 0:
            print(f"y={y}..{y+10}: dark_px={len(xs)}, xs=[{xs.min()}..{xs.max()}]")

if __name__ == "__main__":
    find_q8_options()
