"""
Extract images from a Word file and print their dimensions.
Usage: .\.venv\Scripts\python.exe scripts/extract_docx_images.py <docx_path> [output_dir]
"""
import sys
from pathlib import Path
from docx import Document
from PIL import Image
import io

def extract_images(docx_path: str, output_dir: str = None):
    p = Path(docx_path)
    if not p.exists():
        print(f"ERROR: {docx_path} not found")
        sys.exit(1)

    out_dir = Path(output_dir) if output_dir else p.parent / (p.stem + "_images")
    out_dir.mkdir(parents=True, exist_ok=True)

    doc = Document(str(p))
    images = []
    for rel in doc.part.rels.values():
        if "image" in rel.target_ref:
            blob = rel.target_part.blob
            images.append(blob)

    print(f"File: {p.name}")
    print(f"Total images: {len(images)}")
    print(f"Output dir: {out_dir}")
    print()

    # Count groups of 4-line-only images (potential missing_stem)
    missing_stem_count = 0
    for i, blob in enumerate(images):
        q_num = i + 1
        try:
            im = Image.open(io.BytesIO(blob))
            w, h = im.size
            # Save
            ext = "png"
            out_path = out_dir / f"q{q_num:03d}.{ext}"
            im.save(str(out_path), format="PNG")
            print(f"  q{q_num:03d}: {w}x{h}")
        except Exception as e:
            print(f"  q{q_num:03d}: ERROR {e}")

    print()
    print(f"Done. {len(images)} images extracted to {out_dir}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/extract_docx_images.py <docx_path> [output_dir]")
        sys.exit(1)
    extract_images(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
