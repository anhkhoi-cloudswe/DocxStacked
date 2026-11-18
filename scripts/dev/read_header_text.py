import numpy as np
from PIL import Image

def read_header_text():
    im = Image.open("data/inspect_prn232/top_left_slice.png")
    arr = np.array(im)
    dark = (arr.mean(2) < 170)
    print("ASCII art of header y=20..40, x=15..150:")
    for r in range(20, 40):
        line = "".join(["#" if dark[r, c] else " " for c in range(15, 150)])
        print(f"{r:2d}: {line}")

    print("\nASCII art of header y=60..85, x=15..150:")
    for r in range(60, 85):
        line = "".join(["#" if dark[r, c] else " " for c in range(15, 150)])
        print(f"{r:2d}: {line}")

if __name__ == "__main__":
    read_header_text()
