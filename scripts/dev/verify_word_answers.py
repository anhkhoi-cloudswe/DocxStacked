from docx import Document
from pathlib import Path

doc_path = Path("data/output/CSD202/CSD202 - SU26 - FE.docx")
doc = Document(str(doc_path))
print(f"Total paragraphs in Word document: {len(doc.paragraphs)}")
print("\nFirst 12 questions in Word document:")
for i in range(1, 25, 2):
    q_num = (i // 2) + 1
    p_text = doc.paragraphs[i].text
    runs = doc.paragraphs[i].runs
    runs_info = ", ".join([f"'{r.text}' (size={r.font.size.pt if r.font.size else 'None'}pt, bold={r.bold})" for r in runs])
    print(f"  Q{q_num:02d}: text=\"{p_text}\" | runs=[{runs_info}]")

