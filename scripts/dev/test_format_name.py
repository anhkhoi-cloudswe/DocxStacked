import re

def clean_exam_title(raw_title: str) -> str:
    if not raw_title: return ""
    t = re.sub(r"^\(\d+\)\s*", "", raw_title.strip())
    t = re.sub(r"\s*\|\s*FuOverflow\s*Community.*$", "", t, flags=re.I).strip()
    badge_regex = r"^(?:\[?(?:Đề\s*Thi\s*FE|Đề\s*Thi\s*PE|Đề\s*thi\s*FE|Đề\s*thi\s*PE|Tài\s*Liệu|Tài\s*liệu)\]?[\s\-_:]*)+"
    t = re.sub(badge_regex, "", t, flags=re.I).strip()
    return t

def format_name(code: str, raw_title: str) -> str:
    cleaned = clean_exam_title(raw_title)
    cleaned = re.sub(r'[\\/*?:"<>|]', "", cleaned).strip()
    if cleaned.lower().endswith(".docx"):
        cleaned = cleaned[:-5].strip()
        
    cleaned = re.sub(rf"^{re.escape(code)}[\s\-_]+(?:\[?(?:Đề\s*Thi\s*FE|Đề\s*Thi\s*PE)\]?[\s\-_]+)?{re.escape(code)}[\s\-_]+", f"{code} - ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(rf"^{re.escape(code)}[\s\-_]+{re.escape(code)}[\s\-_]+", f"{code} - ", cleaned, flags=re.IGNORECASE)

    if not cleaned.upper().startswith(code):
        cleaned = f"{code} - {cleaned}"
    return f"{cleaned}.docx"

titles = [
    "PRN232 - Đề Thi FE - PRN232 - SU26 - B5 - FE",
    "(2) Đề Thi FE - PRN232 - SU25 - Final Exam",
    "PRN232 - SU25 - Final Exam",
    "CSD202 - SU26 - FE",
    "SP 2024 - RE",
]
for t in titles:
    print(f"{repr(t)} -> {repr(format_name('PRN232' if 'PRN' in t or 'SP' in t else 'CSD202', t))}")
