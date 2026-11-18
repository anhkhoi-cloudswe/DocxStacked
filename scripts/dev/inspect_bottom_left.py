from PIL import Image

def inspect_bottom_left():
    im = Image.open("data/raw/PRN232/exam_194_su25/q01_Q1.webp").convert("RGB")
    im.crop((0, 680, 250, 780)).save("data/inspect_prn232/bottom_left_slice.png")
    im.crop((0, 0, 250, 150)).save("data/inspect_prn232/top_left_slice.png")
    print("Saved slices")

if __name__ == "__main__":
    inspect_bottom_left()
