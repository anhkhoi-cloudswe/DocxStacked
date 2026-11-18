from PIL import Image
import numpy as np

def inspect_q8_prefix():
    im = Image.open("data/raw/PRN232/exam_194_su25/q08_Q8.webp").convert("RGB")
    arr = np.array(im)
    
    # In row y=106..122, x=130..170
    slice_q8 = arr[106:122, 130:175]
    dark = (slice_q8.mean(2) < 170)
    print("ASCII art of Q8 y=106..122, x=130..175:")
    for r in range(dark.shape[0]):
        line = "".join(["#" if dark[r, c] else " " for c in range(45)])
        print(f"{r:2d}: {line}")

if __name__ == "__main__":
    inspect_q8_prefix()
