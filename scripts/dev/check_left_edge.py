import numpy as np
from PIL import Image

def check_left_edge():
    im = Image.open("data/raw/PRN232/exam_194_su25/q01_Q1.webp").convert("RGB")
    arr = np.array(im)
    print("Shape:", arr.shape)
    
    # Save a slice of Q1 around the left margin: x from 100 to 300, y from 90 to 250
    crop_slice = im.crop((120, 90, 300, 250))
    crop_slice.save("data/inspect_prn232/q01_left_margin_slice.png")
    
    # Check column means around 120..180
    for x in range(130, 180, 2):
        col = arr[90:250, x]
        dark_cnt = ((col.mean(1) < 160)).sum()
        print(f"x={x}: dark_px={dark_cnt}, col_mean={col.mean():.1f}")

if __name__ == "__main__":
    check_left_edge()
