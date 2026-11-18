import sqlite3
import re

def clean_comment_text(raw_text: str) -> str:
    if not raw_text: return ""
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    if lines:
        time_idx = -1
        for i, ln in enumerate(lines):
            if re.search(r"(?:lúc\s+\d{1,2}:\d{2}|\b\d{1,2}\/\d{1,2}\/\d{2,4}\b)", ln, re.IGNORECASE):
                time_idx = i
                break
        if time_idx != -1:
            if time_idx + 1 < len(lines):
                return " ".join(lines[time_idx + 1:]).strip()
            else:
                return ""
    return re.sub(r"\s+", " ", raw_text).strip()

def clean_db_comments():
    conn = sqlite3.connect("data/docxstacked.db")
    cursor = conn.cursor()
    
    rows = cursor.execute("SELECT id, raw_text, upvotes FROM comments").fetchall()
    updated = 0
    for cid, txt, upvotes in rows:
        cleaned = clean_comment_text(txt)
        
        # Check negative score in old txt
        new_upvotes = upvotes
        if (upvotes is None or upvotes == 0) and txt:
            lines = [ln.strip() for ln in txt.splitlines() if ln.strip()]
            for ln in lines:
                m_neg = re.fullmatch(r"(-\d+)", ln)
                if m_neg:
                    new_upvotes = int(m_neg.group(1))
                    break
                    
        if cleaned != txt or new_upvotes != upvotes:
            cursor.execute("UPDATE comments SET raw_text=?, upvotes=? WHERE id=?", (cleaned, new_upvotes, cid))
            updated += 1
            
    conn.commit()
    print(f"Total comments checked: {len(rows)}")
    print(f"Comments cleaned: {updated}")

if __name__ == "__main__":
    clean_db_comments()
