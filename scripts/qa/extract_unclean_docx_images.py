import docx
from pathlib import Path
from PIL import Image

doc_path = Path("data/output/MLN122/MLN122 - SU26 - RE.docx")
doc = docx.Document(str(doc_path))
unclean_qs = [6, 15, 17, 26, 28, 37, 38, 45, 54]

out_dir = Path("docs/qa/docx_extracted_unclean")
out_dir.mkdir(parents=True, exist_ok=True)

curr_q = None
q_to_img = {}

for p in doc.paragraphs:
    t = p.text.strip()
    if t.startswith("Câu ") and t.endswith(":"):
        try:
            curr_q = int(t.replace("Câu ", "").replace(":", ""))
        except:
            curr_q = None
    elif curr_q is not None and curr_q in unclean_qs:
        xml = p._element.xml
        import re
        m = re.search(r'r:embed="(rId\d+)"', xml)
        if m:
            rid = m.group(1)
            target = doc.part.rels[rid].target_ref
            # target is e.g. media/image14.png
            img_part = doc.part.related_parts[rid]
            img_bytes = img_part.blob
            out_file = out_dir / f"cau_{curr_q:02d}.png"
            out_file.write_bytes(img_bytes)
            im = Image.open(out_file)
            print(f"Q{curr_q:02d}: target={target}, size={im.size}, saved to {out_file}")
            q_to_img[curr_q] = (target, im.size, out_file)
        if t:
            curr_q = None
