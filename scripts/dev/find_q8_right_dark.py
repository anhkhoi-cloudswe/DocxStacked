import numpy as np
from PIL import Image

def find_q8_right_dark():
    im = Image.open("data/raw/PRN232/exam_194_su25/q08_Q8.webp").convert("RGB")
    arr = np.array(im)
    dark = (arr.mean(2) < 180) & ((arr.max(2) - arr.min(2)) < 60)
    
    # check dark pixels where x >= 810
    ys, xs = np.where(dark[:, 810:])
    if len(xs) > 0:
        actual_xs = xs + 810
        print(f"Right side dark pixels: count={len(xs)}, xs min={actual_xs.min()}, max={actual_xs.max()}, ys min={ys.min()}, max={ys.max()}")
        im.crop((actual_xs.min()-10, ys.min()-10, actual_xs.max()+10, ys.max()+10)).save("data/inspect_prn232/q08_right_crop.png")

if __name__ == "__main__":
    find_q8_right_dark()
