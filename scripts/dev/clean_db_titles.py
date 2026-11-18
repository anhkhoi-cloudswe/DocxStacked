import sqlite3
import re
from pathlib import Path

def clean_exam_title(raw_title: str) -> str:
    if not raw_title: return ""
    t = re.sub(r"^\(\d+\)\s*", "", raw_title.strip())
    t = re.sub(r"\s*\|\s*FuOverflow\s*Community.*$", "", t, flags=re.I).strip()
    badge_regex = r"^(?:\[?(?:Đề\s*Thi\s*FE|Đề\s*Thi\s*PE|Đề\s*thi\s*FE|Đề\s*thi\s*PE|Tài\s*Liệu|Tài\s*liệu)\]?[\s\-_:]*)+"
    t = re.sub(badge_regex, "", t, flags=re.I).strip()
    return t

def clean_all_titles():
    conn = sqlite3.connect("data/docxstacked.db")
    cursor = conn.cursor()
    
    rows = cursor.execute("SELECT id, subject_id, title FROM exams").fetchall()
    
    updated = []
    for eid, sid, title in rows:
        cleaned = clean_exam_title(title)
        if cleaned != title:
            updated.append((eid, sid, title, cleaned))
            cursor.execute("UPDATE exams SET title=?, updated_at=datetime('now') WHERE id=?", (cleaned, eid))
            
    conn.commit()
    print(f"Total exams checked: {len(rows)}")
    print(f"Total titles cleaned: {len(updated)}")
    for item in updated:
        print(f"ID {item[0]}: {repr(item[2])} -> {repr(item[3])}")

if __name__ == "__main__":
    clean_all_titles()
