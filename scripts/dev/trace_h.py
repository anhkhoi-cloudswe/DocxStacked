import sqlite3
from backend.app.modules.analysis.analyzer import extract_choice, calculate_consensus

def trace_h():
    conn = sqlite3.connect("data/docxstacked.db")
    cursor = conn.cursor()
    
    # Q2 question_id=886
    comments = cursor.execute("SELECT id, author_hash, raw_text, upvotes FROM comments WHERE question_id=886 ORDER BY id").fetchall()
    print("Tracing comments for Q2 (question_id=886):")
    for c in comments:
        parsed = extract_choice(c[2])
        print(f"Comment {c[0]} | Author {c[1]} | Parsed Choice: {parsed}")
        if "H" in str(parsed):
            print(f"   ---> FOUND H! Raw text:\n{c[2]}")

if __name__ == "__main__":
    trace_h()
