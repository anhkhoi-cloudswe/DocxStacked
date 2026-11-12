from pathlib import Path
import re
import json
from docx import Document
from docx.oxml import parse_xml

def extract_docx_pairs(docx_path: Path, output_subdir: Path):
    doc = Document(str(docx_path))
    output_subdir.mkdir(parents=True, exist_ok=True)
    images_dir = output_subdir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    pairs = []
    paragraphs = doc.paragraphs

    q_idx = 0
    i = 0
    while i < len(paragraphs):
        p = paragraphs[i]
        # Find images in this paragraph
        blip_rids = []
        for r in p.runs:
            # find all blip r:embed
            for elem in r._r.iter():
                if elem.tag.endswith("blip"):
                    embed = elem.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed")
                    if embed:
                        blip_rids.append(embed)

        if blip_rids:
            q_idx += 1
            rId = blip_rids[0]
            image_part = doc.part.related_parts[rId]
            image_bytes = image_part.blob
            # Determine extension
            ext = image_part.content_type.split("/")[-1].replace("jpeg", "jpg")
            img_filename = f"q{q_idx:03d}.{ext}"
            img_path = images_dir / img_filename
            img_path.write_bytes(image_bytes)

            # Next paragraph should be answer
            ans_letter = None
            ans_full_text = ""
            if i + 1 < len(paragraphs):
                ans_p = paragraphs[i + 1]
                ans_text = ans_p.text.strip()
                ans_full_text = ans_text
                # User rule: "chữ cái là ký tự đầu của dòng đáp án nếu thuộc A-D"
                m = re.match(r"^([A-D])\b", ans_text, re.IGNORECASE)
                if m:
                    ans_letter = m.group(1).upper()

            pairs.append({
                "index": q_idx,
                "image_file": str(img_path.name),
                "image_path": str(img_path.resolve()),
                "expected_answer": ans_letter,
                "full_answer_text": ans_full_text,
            })
            i += 2  # skip answer paragraph
        else:
            i += 1

    metadata_path = output_subdir / "ground_truth.json"
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(pairs, f, ensure_ascii=False, indent=2)

    print(f"Extracted from {docx_path.name}: {len(pairs)} questions.")
    valid_answers = sum(1 for p in pairs if p["expected_answer"] is not None)
    print(f"  Valid A-D answers: {valid_answers}/{len(pairs)}")
    return pairs

if __name__ == "__main__":
    eval_dir = Path("data/eval")
    eval_dir.mkdir(parents=True, exist_ok=True)

    f1 = Path("C:/AK/HOCKI8/MLN122/MLN122_FE/MLN122 - FA25 - C1FE.docx")
    f2 = Path("C:/AK/HOCKI8/PRN232/PRN232_FE/PRN232 - SP26.docx")

    extract_docx_pairs(f1, eval_dir / "MLN122")
    extract_docx_pairs(f2, eval_dir / "PRN232")

