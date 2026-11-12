from pathlib import Path
import os

print("Searching for MLN122 and PRN232 files...")
roots = ["c:/AK", "C:/Users/Admin", "C:/"]

found = []
for root in ["C:/AK", "C:/Users/Admin/Downloads", "C:/Users/Admin/Desktop", "C:/Users/Admin/Documents"]:
    p_root = Path(root)
    if p_root.exists():
        for p in p_root.rglob("*"):
            try:
                name_lower = p.name.lower()
                if ("mln122" in name_lower or "prn232" in name_lower) and p.suffix.lower() in [".docx", ".doc", ".pdf", ".zip"]:
                    print("Found:", p)
                    found.append(p)
            except Exception:
                pass

print(f"Total found: {len(found)}")

