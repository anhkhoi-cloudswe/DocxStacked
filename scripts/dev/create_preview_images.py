from PIL import Image, ImageDraw, ImageFont
import glob
from pathlib import Path

# Create a visual preview of the Word document page layout
# Letter page simulation: 816 x 1056 px (representing 8.5 x 11 inches at 96 dpi)
page = Image.new("RGB", (816, 1056), (255, 255, 255))
draw = ImageDraw.Draw(page)

# Margins: 1 inch = 96 px
margin_x = 96
curr_y = 96

# Load sample cropped questions: Q1 and Q2
q1_path = Path("data/cropped/CSD202/exam_1/q001.png")
q2_path = Path("data/cropped/CSD202/exam_1/q002.png")

# Use basic font or default
try:
    font_ans = ImageFont.truetype("arialbd.ttf", 26) # Bold ~20pt
    font_note = ImageFont.truetype("arial.ttf", 14)  # Normal ~11pt
except Exception:
    font_ans = ImageFont.load_default()
    font_note = ImageFont.load_default()

# 1. Question 1
if q1_path.exists():
    im1 = Image.open(q1_path)
    page.paste(im1, (margin_x, curr_y))
    curr_y += im1.height + 8
    
    # Answer line: 'B' in bold red 20pt
    draw.text((margin_x, curr_y), "B", fill=(238, 0, 0), font=font_ans)
    curr_y += 42

# 2. Question 2
if q2_path.exists():
    im2 = Image.open(q2_path)
    page.paste(im2, (margin_x, curr_y))
    curr_y += im2.height + 8
    
    # Answer line: '? (cần kiểm tra lại)'
    draw.text((margin_x, curr_y), "?", fill=(238, 0, 0), font=font_ans)
    draw.text((margin_x + 24, curr_y + 8), " (cần kiểm tra lại)", fill=(127, 127, 127), font=font_note)
    curr_y += 42

# Page border simulation
draw.rectangle([0, 0, 815, 1055], outline=(200, 200, 200), width=1)

output_preview = Path("docs/screenshots/sample_docx_preview.png")
output_preview.parent.mkdir(parents=True, exist_ok=True)
page.save(output_preview)
print("Saved visual preview at:", output_preview)

# Also create side-by-side comparison of raw vs cropped for Q1
raw_q1 = Image.open("data/raw/CSD202/exam_1_SU26/q01_Q1.webp")
crop_q1 = Image.open("data/cropped/CSD202/exam_1/q001.png")

# Resize raw to 50% for comparison display
raw_scaled = raw_q1.resize((960, 360))
cmp_img = Image.new("RGB", (960, 360 + crop_q1.height + 60), (250, 247, 242))
draw_cmp = ImageDraw.Draw(cmp_img)

# Title 1
draw_cmp.text((10, 10), "1. ANH GOC (1920x720 co thanh xanh MULTIPLE CHOICE va watermark)", fill=(31, 27, 22))
cmp_img.paste(raw_scaled, (0, 30))

# Title 2
draw_cmp.text((10, 400), "2. ANH DA CAT GON (giu nguyen cau hoi va 4 dap an A-D)", fill=(31, 27, 22))
cmp_img.paste(crop_q1, (10, 425))

output_cmp = Path("docs/screenshots/raw_vs_cropped_comparison.png")
cmp_img.save(output_cmp)
print("Saved raw vs cropped comparison at:", output_cmp)

