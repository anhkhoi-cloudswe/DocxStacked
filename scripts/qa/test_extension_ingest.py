import os
import sys
import base64
import json
import sqlite3
import time
from pathlib import Path
from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))

from backend.app.main import app
from backend.app.core.config import get_settings

settings = get_settings()

def run_test():
    client = TestClient(app)
    
    print("=" * 60)
    print("TEST 1: Security check on /api/ingest")
    print("=" * 60)
    
    # 1. Missing or wrong token check
    res_bad_token = client.post(
        "/api/ingest",
        json={"subject_code": "MLN122", "exam_title": "MLN122 - SU26 - RE", "questions": []},
        headers={"X-Ingest-Token": "wrong_token_xyz"}
    )
    print(f"Missing/Wrong token check status: {res_bad_token.status_code} -> {res_bad_token.json().get('detail')}")
    assert res_bad_token.status_code == 401

    # 2. Origin header security check
    res_bad_origin = client.post(
        "/api/ingest",
        json={"subject_code": "MLN122", "exam_title": "MLN122 - SU26 - RE", "questions": []},
        headers={
            "X-Ingest-Token": settings.INGEST_TOKEN,
            "Origin": "https://malicious-website.com"
        }
    )
    print(f"Malicious Origin check status: {res_bad_origin.status_code} -> {res_bad_origin.json().get('detail')}")
    assert res_bad_origin.status_code == 403

    print("\n" + "=" * 60)
    print("TEST 2: Ingest MLN122 - SU26 - RE (Preserve title, no renaming)")
    print("=" * 60)
    
    db_path = Path("data/docxstacked.db")
    if not db_path.exists():
        print(f"Error: {db_path} does not exist!")
        return

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Target exam ID 136
    cursor.execute("SELECT * FROM exams WHERE id = 136")
    exam = cursor.fetchone()
    if not exam:
        print("Exam ID 136 not found in DB!")
        return

    exam_id = exam["id"]
    original_title = exam["title"]
    source_url = exam["url"] or "https://fuoverflow.com/threads/mln122-su26-re.7207/"
    term = exam["term"] or "SU26"
    print(f"Original Database Exam: ID={exam_id}, Title='{original_title}', URL='{source_url}', Term='{term}'")
    
    # Fetch questions
    cursor.execute("SELECT * FROM questions WHERE exam_id = ? ORDER BY `index` ASC", (exam_id,))
    questions = cursor.fetchall()
    print(f"Total questions found in DB: {len(questions)}")
    
    ingest_questions = []
    
    for q in questions:
        q_id = q["id"]
        q_idx = q["index"]
        raw_img_path = Path(q["local_image_path"]) if q["local_image_path"] else None
        
        b64_data = ""
        if raw_img_path and raw_img_path.exists():
            b64_data = base64.b64encode(raw_img_path.read_bytes()).decode("utf-8")
        elif q["cropped_image_path"] and Path(q["cropped_image_path"]).exists():
            b64_data = base64.b64encode(Path(q["cropped_image_path"]).read_bytes()).decode("utf-8")
        else:
            b64_data = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        
        cursor.execute("SELECT * FROM comments WHERE question_id = ?", (q_id,))
        comments = cursor.fetchall()
        c_list = []
        for c in comments:
            c_list.append({
                "comment_id": str(c["comment_id"] or ""),
                "author_hash": c["author_hash"] or "anon",
                "raw_text": c["raw_text"] or "",
                "upvotes": c["upvotes"] or 0,
                "is_reply": bool(c["is_reply"]),
                "posted_at": c["posted_at"] or ""
            })
            
        ingest_questions.append({
            "index": q_idx,
            "media_id": q["media_id"] or f"media_{q_idx}",
            "media_url": q["media_url"] or f"https://fuoverflow.com/media/{q_idx}/",
            "file_name": q["file_name"] or f"question_{q_idx:03d}.png",
            "image_base64": b64_data,
            "comments": c_list
        })
        
    conn.close()
    
    # We pass title extracted from page thread
    payload = {
        "subject_code": "MLN122",
        "exam_title": "MLN122 - SU26 - RE",
        "exam_url": source_url,
        "term": term,
        "exam_type": "RE",
        "questions": ingest_questions,
        "options": {
            "ai_enabled": False
        }
    }
    
    print(f"Sending payload to POST /api/ingest: {len(ingest_questions)} questions with X-Ingest-Token...")
    t0 = time.time()
    response = client.post(
        "/api/ingest",
        json=payload,
        headers={
            "X-Ingest-Token": settings.INGEST_TOKEN,
            "Origin": "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
        }
    )
    t_elapsed = time.time() - t0
    
    print(f"\nResponse HTTP Status: {response.status_code} ({t_elapsed:.2f}s)")
    if response.status_code == 200:
        data = response.json()
        print("=" * 60)
        print("INGESTION & WORD GENERATION RESULTS")
        print("=" * 60)
        print(f"Status              : {data.get('status')}")
        print(f"Exam ID             : {data.get('exam_id')}")
        print(f"Exam Title (Retained): '{data.get('exam_title')}'")
        print(f"Questions Ingested  : {data.get('questions_ingested')}")
        print(f"Comments Ingested   : {data.get('comments_ingested')}")
        print(f"Docx Filename       : {data.get('docx_filename')}")
        print(f"Docx Path           : {data.get('docx_path')}")
        
        docx_path = Path(data.get("docx_path", ""))
        if docx_path.exists():
            size_kb = docx_path.stat().st_size / 1024
            print(f"Docx File Size      : {size_kb:.2f} KB")
            print(f"Download URL        : {data.get('download_url')}")
            
            # Assert title and filename properties
            assert data.get('exam_title') == original_title, f"Title changed! Expected '{original_title}', got '{data.get('exam_title')}'"
            assert "Extension Ingested" not in data.get('exam_title'), "Suffix '(Extension Ingested)' must not be in title!"
            assert "MLN122 - MLN122" not in data.get('docx_filename'), "Duplicate subject prefix in filename!"
            print("\n[SUCCESS] Word file and title requirements fully verified!")
        else:
            print("\n[WARNING] Docx file was not found on disk.")
    else:
        print(f"Error: {response.text}")

if __name__ == "__main__":
    run_test()
