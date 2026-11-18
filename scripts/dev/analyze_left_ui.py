import numpy as np
from PIL import Image

def analyze_left_ui():
    im = Image.open("data/raw/PRN232/exam_194_su25/q01_Q1.webp").convert("RGB")
    arr = np.array(im)
    
    # Save a crop of the left 300 columns
    im.crop((0, 0, 400, 780)).save("data/inspect_prn232/q01_left_400.png")
    
    # Check what is in columns 0..200
    # Let's print out background color and where the vertical line or separator is
    for x in range(0, 200, 5):
        col = arr[:, x]
        mean_rgb = col.mean(0)
        print(f"x={x:3d}: mean_rgb=({mean_rgb[0]:.1f}, {mean_rgb[1]:.1f}, {mean_rgb[2]:.1f})")

if __name__ == "__main__":
    analyze_left_ui()
