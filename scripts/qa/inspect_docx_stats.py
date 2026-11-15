import io
from pathlib import Path
import sys
import zipfile
from PIL import Image

def inspect_all_docx():
    output_dir = Path("data/output")
    docx_files = sorted(output_dir.glob("*/*.docx"))
    
    print("=" * 90)
    print("DOCX STATS INSPECTOR - EXTRACTED DIRECTLY FROM FILES IN data/output")
    print("=" * 90)
    
    for docx_path in docx_files:
        size_bytes = docx_path.stat().st_size
        size_kb = size_bytes / 1024
        
        try:
            with zipfile.ZipFile(docx_path) as z:
                media_files = [f for f in z.namelist() if f.startswith("word/media/")]
                widths = []
                heights = []
                
                for mf in sorted(media_files):
                    raw_data = z.read(mf)
                    try:
                        im = Image.open(io.BytesIO(raw_data))
                        widths.append(im.width)
                        heights.append(im.height)
                    except Exception:
                        pass
                
                print(f"\nFile: {docx_path.parent.name}/{docx_path.name}")
                print(f"  Size: {size_bytes:,} bytes ({size_kb:.1f} KB)")
                print(f"  Image count: {len(widths)}")
                if widths:
                    min_w, max_w = min(widths), max(widths)
                    min_h, max_h = min(heights), max(heights)
                    print(f"  Widths (px) : min = {min_w}, max = {max_w}")
                    print(f"  Heights (px): min = {min_h}, max = {max_h}")
                    
                    # Highlight specific questions mentioned by user
                    if "FA 2024 - RE" in docx_path.name:
                        print(f"  >>> FA24 RE Width Min Verified: {min_w} px (Report correction: was reported 338, actual is {min_w})")
                    if "SP 2024 - FE" in docx_path.name and "PRM392" in docx_path.name:
                        print(f"  >>> PRM392 FE Width Max Verified: {max_w} px (Report correction: was reported 460, actual is {max_w})")
                else:
                    print("  No images found (empty or non-media docx).")
        except zipfile.BadZipFile:
            print(f"\nFile: {docx_path.parent.name}/{docx_path.name}")
            print(f"  Size: {size_bytes:,} bytes")
            print("  [INVALID / NON-ZIP DOCX FILE - e.g. mock test file]")

if __name__ == "__main__":
    inspect_all_docx()
