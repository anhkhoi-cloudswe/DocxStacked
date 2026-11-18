import numpy as np
from PIL import Image

def read_slices():
    im_top = Image.open("data/inspect_prn232/top_left_slice.png")
    arr_top = np.array(im_top)
    dark_top = (arr_top.mean(2) < 170)
    print("Top slice dark pixels in y=0..100, x=0..250:")
    for y in range(0, 100, 10):
        c = dark_top[y:y+10, :].sum()
        if c > 0:
            ys, xs = np.where(dark_top[y:y+10, :])
            print(f"y={y}..{y+10}: dark={c}, xs=[{xs.min()}..{xs.max()}]")

    im_bot = Image.open("data/inspect_prn232/bottom_left_slice.png")
    arr_bot = np.array(im_bot)
    dark_bot = (arr_bot.mean(2) < 170)
    print("\nBottom slice dark pixels in y=680..780, x=0..250:")
    for y in range(0, 100, 10):
        c = dark_bot[y:y+10, :].sum()
        if c > 0:
            ys, xs = np.where(dark_bot[y:y+10, :])
            print(f"y={680+y}..{680+y+10}: dark={c}, xs=[{xs.min()}..{xs.max()}]")

if __name__ == "__main__":
    read_slices()
