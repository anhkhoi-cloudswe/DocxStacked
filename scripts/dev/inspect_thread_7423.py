import json
from pathlib import Path

def inspect_thread_7423():
    p = Path("data/ingest_debug/payload_PRN232_20261118_100524.json")
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    print("Exam Title:", data.get("title"))
    print("Exam URL:", data.get("url"))
    questions = data.get("questions", [])
    print(f"Total questions: {len(questions)}")
    
    # Check Q20..Q50
    print("\n--- Inspecting Q20..Q25 comments ---")
    for q in questions[19:25]:
        q_idx = q.get("index")
        comments = q.get("comments", [])
        print(f"\nQuestion {q_idx} (comments count: {len(comments)}):")
        for c in comments[:3]:
            print(f"  Comment: id={c.get('comment_id')}, author={c.get('author_name')}, upvotes={c.get('upvotes')}")
            raw = c.get("raw_text", "")
            print(f"  raw_text repr (len={len(raw)}): {repr(raw[:100])}")

if __name__ == "__main__":
    inspect_thread_7423()
