import numpy as np
from PIL import Image

def inspect_q8_right():
    im = Image.open("data/raw/PRN232/exam_194_su25/q08_Q8.webp").convert("RGB")
    arr = np.array(im)
    sub = arr[50:750, 810:1920]
    print("Right side shape:", sub.shape)
    print("Right side min RGB:", sub.min(axis=(0,1)))
    print("Right side max RGB:", sub.max(axis=(0,1)))
    print("Right side mean RGB:", sub.mean(axis=(0,1)))
    dark = (sub.mean(2) < 180)
    print("Right side dark pixels count:", dark.sum())

if __name__ == "__main__":
    inspect_q8_right()
