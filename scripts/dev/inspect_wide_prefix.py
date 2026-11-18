from PIL import Image
import numpy as np

def inspect_wide_prefix():
    im = Image.open("data/raw/PRN232/exam_194_su25/q08_Q8.webp").convert("RGB")
    arr = np.array(im)
    
    # In row y=104..124, x=100..180
    slice_q8 = arr[104:124, 100:180]
    dark = (slice_q8.mean(2) < 170)
    print("ASCII art of Q8 y=104..124, x=100..180:")
    for r in range(dark.shape[0]):
        line = "".join(["#" if dark[r, c] else " " for c in range(80)])
        print(f"{r:2d}: {line}")

if __name__ == "__main__":
    inspect_wide_prefix()
