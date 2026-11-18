from PIL import Image
import numpy as np

def dump_regions():
    im = Image.open("data/raw/PRN232/exam_194_su25/q01_Q1.webp").convert("RGB")
    # let's save crops of various areas:
    # 1. x: 0..170, y: 0..300
    im.crop((0, 0, 170, 300)).save("data/inspect_prn232/q01_area_0_170.png")
    # 2. x: 170..810, y: 0..300
    im.crop((170, 0, 810, 300)).save("data/inspect_prn232/q01_area_170_810.png")
    # 3. x: 810..1920, y: 0..300
    im.crop((810, 0, 1920, 300)).save("data/inspect_prn232/q01_area_810_1920.png")
    # 4. full height slice around x: 140..220
    im.crop((140, 50, 250, 300)).save("data/inspect_prn232/q01_left_transition.png")

    print("Crops saved. Now checking Q8...")
    im8 = Image.open("data/raw/PRN232/exam_194_su25/q08_Q8.webp").convert("RGB")
    im8.crop((150, 50, 810, 400)).save("data/inspect_prn232/q08_main_area.png")
    im8.crop((0, 0, 810, 780)).save("data/inspect_prn232/q08_left_half.png")

if __name__ == "__main__":
    dump_regions()
