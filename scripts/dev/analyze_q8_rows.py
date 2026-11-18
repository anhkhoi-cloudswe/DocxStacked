import numpy as np
from PIL import Image

def analyze_q8_rows():
    im = Image.open("data/raw/PRN232/exam_194_su25/q08_Q8.webp").convert("RGB")
    arr = np.array(im)
    dark = (arr.mean(2) < 180) & ((arr.max(2) - arr.min(2)) < 60)
    
    for y_range in [(107, 120), (150, 162), (170, 185), (190, 205), (210, 225)]:
        ys, xs = np.where(dark[y_range[0]:y_range[1], :])
        if len(xs) > 0:
            print(f"y in {y_range}: xs min={xs.min()}, max={xs.max()}, count={len(xs)}")
            # print histogram of xs
            xs_left = (xs < 170).sum()
            xs_mid = ((xs >= 170) & (xs < 810)).sum()
            xs_right = (xs >= 810).sum()
            print(f"   xs_left (<170): {xs_left}, xs_mid (170..810): {xs_mid}, xs_right (>=810): {xs_right}")

if __name__ == "__main__":
    analyze_q8_rows()
