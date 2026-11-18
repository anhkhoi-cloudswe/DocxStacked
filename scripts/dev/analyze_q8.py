import numpy as np
from PIL import Image

def analyze_q8():
    im = Image.open("data/raw/PRN232/exam_194_su25/q08_Q8.webp").convert("RGB")
    arr = np.array(im)
    
    # In Q8, what did cropper do?
    # Cropper box was: (170, 107, 578, 121)
    # Why did it stop at y=121?
    # Where are dark pixels between x=170 and x=810 in Q8?
    q_region = arr[:, 170:809]
    dark = (q_region.mean(2) < 160) & ((q_region.max(2) - q_region.min(2)) < 50)
    
    # row sums of dark pixels
    row_sums = dark.sum(axis=1)
    print("Row sums of dark pixels in Q8 (x in 170..809):")
    for y in range(0, 780):
        if row_sums[y] > 5:
            print(f"y={y:3d}: dark_count={row_sums[y]}")

if __name__ == "__main__":
    analyze_q8()
