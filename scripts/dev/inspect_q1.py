from PIL import Image
import numpy as np

def inspect_q1():
    im = Image.open("data/raw/PRN232/exam_194_su25/q01_Q1.webp").convert("RGB")
    arr = np.array(im)
    dark = (arr.mean(2) < 170) & ((arr.max(2) - arr.min(2)) < 50)
    for y in range(100, 250, 10):
        row_dark = dark[y:y+10, :]
        ys, xs = np.where(row_dark)
        if len(xs) > 0:
            print(f"Q1 y={y}..{y+10}: dark_px={len(xs)}, xs=[{xs.min()}..{xs.max()}]")

if __name__ == "__main__":
    inspect_q1()
