from docx import Document
from pathlib import Path
import re

files = [
    Path("C:/AK/HOCKI8/MLN122/MLN122_FE/MLN122 - FA25 - C1FE.docx"),
    Path("C:/AK/HOCKI8/PRN232/PRN232_FE/PRN232 - SP26.docx"),
]

for doc_path in files:
    print(f"\n======================================")
    print(f"Inspecting: {doc_path.name}")
    print(f"Exists: {doc_path.exists()}, Size: {doc_path.stat().st_size} bytes")
    doc = Document(str(doc_path))
    print(f"Total paragraphs: {len(doc.paragraphs)}")

    # Sample first 10 paragraphs
    for i in range(min(15, len(doc.paragraphs))):
        p = doc.paragraphs[i]
        text = p.text.strip()
        # Check if contains image run
        has_img = False
        for r in p.runs:
            if "drawing" in r._r.xml:
                has_img = True
                break
        print(f"  P[{i:02d}] (has_img={has_img}): '{text[:80]}'")

