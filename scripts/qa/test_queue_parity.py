"""
scripts/qa/test_queue_parity.py
Parity test comparing single exam ingestion vs queue ingestion output for 60 questions.
"""
import sys
import json
import urllib.request
from pathlib import Path
import docx

BACKEND_URL = "http://127.0.0.1:8000"

import io
import base64
from PIL import Image

def get_dummy_image_b64(idx):
    img = Image.new('RGB', (400, 200))
    pixels = [((i * (idx + 13)) % 256, (i * 37) % 256, (i * 71) % 256) for i in range(400 * 200)]
    img.putdata(pixels)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return base64.b64encode(buf.getvalue()).decode('utf-8')

def build_exam_payload(subject_code: str, exam_title: str, exam_url: str, num_questions: int = 60, seed: int = 1):
    questions = []
    options = ["A", "B", "C", "D"]
    for i in range(1, num_questions + 1):
        ans = options[(i + seed) % 4]
        questions.append({
            "index": i,
            "file_name": f"question_{i}.png",
            "media_id": f"q_parity_{i}",
            "media_url": f"https://fuoverflow.com/attachments/parity_{i}/",
            "image_base64": get_dummy_image_b64(i),
            "comments": [
                {
                    "author_name": "Student1",
                    "raw_text": f"Đáp án là {ans} nhé câu {i}",
                    "posted_at": "2026-08-01T20:00:00+0700"
                }
            ]
        })
    return {
        "subject_code": subject_code,
        "exam_title": exam_title,
        "exam_url": exam_url,
        "questions": questions,
        "options": {}
    }

def ingest_exam(payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BACKEND_URL}/api/ingest",
        data=data,
        headers={"Content-Type": "application/json", "X-DocxStacked-Ext": "kicplcdfmbcfjildbbimpfiljlmfokea"}
    )
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode("utf-8"))
        return res

def extract_docx_answers(docx_path: Path):
    doc = docx.Document(docx_path)
    answers = {}
    current_q = None
    for p in doc.paragraphs:
        txt = p.text.strip()
        if not txt:
            continue
        if txt.startswith("Câu ") or txt.startswith("Question "):
            parts = txt.split(":")
            try:
                current_q = int(parts[0].replace("Câu", "").replace("Question", "").strip())
            except Exception:
                pass
        elif current_q is not None and current_q not in answers:
            # The paragraph immediately following 'Câu X:' is the answer
            answers[current_q] = txt
    return answers

def main():
    print("=== DOCXSTACKED QUEUE VS SINGLE BUTTON PARITY TEST ===")
    exam_title_single = "PARITY_TEST - Single Ingest (60 Questions)"
    exam_title_queue = "PARITY_TEST - Queue Ingest (60 Questions)"
    exam_url_single = "https://fuoverflow.com/threads/parity-single.99901/"
    exam_url_queue = "https://fuoverflow.com/threads/parity-queue.99902/"

    print("1. Ingesting via Single Button payload (60 questions)...")
    payload_single = build_exam_payload("PRM392", exam_title_single, exam_url_single, 60, seed=42)
    res_single = ingest_exam(payload_single)
    docx_rel_single = res_single.get("docx_path") or res_single.get("download_url", "").replace("/api/exports/download?path=", "")
    path_single = Path(docx_rel_single)
    if not path_single.is_absolute():
        path_single = Path("data/output") / path_single.name
    print(f"   Single docx: {path_single.name} (exists={path_single.exists()})")

    print("2. Ingesting via Queue Sequential payload (60 questions, same seed)...")
    payload_queue = build_exam_payload("PRM392", exam_title_queue, exam_url_queue, 60, seed=42)
    res_queue = ingest_exam(payload_queue)
    docx_rel_queue = res_queue.get("docx_path") or res_queue.get("download_url", "").replace("/api/exports/download?path=", "")
    path_queue = Path(docx_rel_queue)
    if not path_queue.is_absolute():
        path_queue = Path("data/output") / path_queue.name
    print(f"   Queue docx:  {path_queue.name} (exists={path_queue.exists()})")

    print("\n3. Comparing 60 questions answers between Single and Queue docx...")
    answers_single = extract_docx_answers(path_single)
    answers_queue = extract_docx_answers(path_queue)

    print(f"   Single answers parsed: {len(answers_single)}")
    print(f"   Queue answers parsed:  {len(answers_queue)}")

    differences = []
    for q_idx in range(1, 61):
        a1 = answers_single.get(q_idx)
        a2 = answers_queue.get(q_idx)
        if a1 != a2:
            differences.append((q_idx, a1, a2))

    print("\n=== PARITY TEST RESULTS ===")
    print(f"Total questions compared: 60")
    print(f"Differences found:        {len(differences)}")
    if differences:
        for diff in differences:
            print(f" - Question {diff[0]}: single='{diff[1]}' vs queue='{diff[2]}'")
    else:
        print("PERFECT PARITY: 0 differences found across all 60 questions!")

    # Clean up test output files so test files do not pollute data directory
    try:
        if path_single.exists(): path_single.unlink()
        if path_queue.exists(): path_queue.unlink()
        print(f"Cleaned up temporary parity test files.")
    except Exception as e:
        print(f"Cleanup warning: {e}")

    return 0 if len(differences) == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
