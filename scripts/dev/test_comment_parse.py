import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))

import sqlite3
from backend.app.modules.analysis.parser import parse_comment_text

def test_comments():
    conn = sqlite3.connect("data/docxstacked.db")
    cursor = conn.cursor()
    comments = cursor.execute("SELECT id, raw_text FROM comments WHERE question_id=886 ORDER BY id").fetchall()
    for cid, text in comments:
        parsed = parse_comment_text(text)
        print(f"Comment {cid}: answers={parsed.answers}, raw_text_preview={repr(text[:50])}")
        if parsed.answers and "H" in parsed.answers:
            print(f"   FULL TEXT:\n{text}")

if __name__ == "__main__":
    test_comments()
