import numpy as np
from PIL import Image

def inspect_q8_colors():
    im = Image.open("data/raw/PRN232/exam_194_su25/q08_Q8.webp").convert("RGB")
    arr = np.array(im)
    
    # Check pixels in area (170..809, 120..400)
    sub = arr[120:400, 170:809]
    print("Sub area shape:", sub.shape)
    print("Sub area min RGB:", sub.min(axis=(0,1)))
    print("Sub area max RGB:", sub.max(axis=(0,1)))
    print("Sub area mean RGB:", sub.mean(axis=(0,1)))
    
    # Unique colors in this area:
    reshaped = sub.reshape(-1, 3)
    unique_colors, counts = np.unique(reshaped, axis=0, return_counts=True)
    print(f"Number of unique colors: {len(unique_colors)}")
    top_indices = np.argsort(counts)[::-1][:10]
    for idx in top_indices:
        print(f"Color: {unique_colors[idx]}, count: {counts[idx]}")

if __name__ == "__main__":
    inspect_q8_colors()
