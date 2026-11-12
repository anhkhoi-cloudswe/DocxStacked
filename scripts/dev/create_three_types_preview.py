from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

# Create image showcasing 3 types of questions:
# Type 1: Single choice standard (Q1)
# Type 2: Code block question (Q13)
# Type 3: Tall diagram question (Q37)

q1 = Image.open("data/cropped/CSD202/exam_1/q001.png")
q13 = Image.open("data/cropped/CSD202/exam_1/q013.png")
q37 = Image.open("data/cropped/CSD202/exam_1/q037.png")

total_w = 800
total_h = q1.height + q13.height + q37.height + 220

preview = Image.new("RGB", (total_w, total_h), (250, 247, 242))
draw = ImageDraw.Draw(preview)

try:
    font_title = ImageFont.truetype("arialbd.ttf", 16)
    font_ans = ImageFont.truetype("arialbd.ttf", 24)
except Exception:
    font_title = ImageFont.load_default()
    font_ans = ImageFont.load_default()

y = 20

# 1. Standard Single Choice (Q1)
draw.text((20, y), "Loai 1: Cau hoi tieu chuan (Q1) - Dung kich thuoc 369x172", fill=(31, 27, 22), font=font_title)
y += 30
preview.paste(q1, (20, y))
y += q1.height + 8
draw.text((20, y), "B", fill=(238, 0, 0), font=font_ans)
y += 45

# 2. Code Block Question (Q13)
draw.text((20, y), "Loai 2: Cau hoi co ma lenh / code block rong (Q13) - Kich thuoc 717x186", fill=(31, 27, 22), font=font_title)
y += 30
preview.paste(q13, (20, y))
y += q13.height + 8
draw.text((20, y), "A", fill=(238, 0, 0), font=font_ans)
y += 45

# 3. Diagram / Tall Question (Q37)
draw.text((20, y), "Loai 3: Cau hoi co hinh minh hoa / do thi cao (Q37) - Kich thuoc 384x555", fill=(31, 27, 22), font=font_title)
y += 30
preview.paste(q37, (20, y))
y += q37.height + 8
draw.text((20, y), "C", fill=(238, 0, 0), font=font_ans)

out_path = Path("docs/screenshots/three_question_types.png")
preview.save(out_path)
print("Saved 3 types preview at:", out_path)

