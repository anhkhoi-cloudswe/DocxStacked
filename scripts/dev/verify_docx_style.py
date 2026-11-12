from docx import Document
from docx.shared import Cm, Pt

doc = Document("data/output/CSD202/CSD202 - SU26 - FE.docx")
print("Total paragraphs:", len(doc.paragraphs))
section = doc.sections[0]
print("Page width:", round(section.page_width.cm, 2), "cm")
print("Page height:", round(section.page_height.cm, 2), "cm")
print("Left margin:", round(section.left_margin.cm, 2), "cm")
print("Right margin:", round(section.right_margin.cm, 2), "cm")

for i in range(min(8, len(doc.paragraphs))):
    p = doc.paragraphs[i]
    print(f"P{i:02d}: text={repr(p.text)}")
    for r in p.runs:
        sz = r.font.size.pt if r.font.size else "default"
        col = str(r.font.color.rgb) if r.font.color else "default"
        print(f"   Run: bold={r.bold}, size={sz}, color={col}, text={repr(r.text)}")

