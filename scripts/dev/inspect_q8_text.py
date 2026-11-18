from PIL import Image
import numpy as np

def inspect_q8_text():
    im = Image.open("data/raw/PRN232/exam_194_su25/q08_Q8.webp").convert("RGB")
    arr = np.array(im)
    
    # In row y=107..121, let's see ascii representation of dark pixels
    slice_q8 = arr[106:122, 160:580]
    dark = (slice_q8.mean(2) < 170)
    print("ASCII art of Q8 y=106..122, x=160..240:")
    for r in range(dark.shape[0]):
        line = "".join(["#" if dark[r, c] else " " for c in range(80)])
        print(line)

if __name__ == "__main__":
    inspect_q8_text()
