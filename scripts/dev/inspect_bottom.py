import numpy as np
from PIL import Image

def inspect_bottom():
    im = Image.open("data/raw/PRN232/exam_194_su25/q08_Q8.webp").convert("RGB")
    arr = np.array(im)
    mid = arr[700:780, 160:810]
    dark = (mid.mean(2) < 170) & ((mid.max(2) - mid.min(2)) < 50)
    ys, xs = np.where(dark)
    print("Bottom dark pixels in 160..810:", len(ys))
    if len(ys) > 0:
        print(f"ys=[{ys.min()+700}..{ys.max()+700}], xs=[{xs.min()+160}..{xs.max()+160}]")
        im.crop((xs.min()+150, ys.min()+690, xs.max()+170, ys.max()+710)).save("data/inspect_prn232/bottom_slice.png")

    # What about between y=125 and y=700?
    mid_center = arr[125:700, 160:810]
    dark_c = (mid_center.mean(2) < 170) & ((mid_center.max(2) - mid_center.min(2)) < 50)
    print("Center dark pixels between y=125 and 700:", dark_c.sum())

if __name__ == "__main__":
    inspect_bottom()
