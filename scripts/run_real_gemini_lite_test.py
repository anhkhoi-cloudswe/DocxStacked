import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app.modules.analysis.providers import GeminiProvider
import json

provider = GeminiProvider(model="gemini-flash-lite-latest")
questions_to_test = [
    ("PRN232 SP26 FE - Câu 01", Path("data/cropped/PRN232/exam_193/q001.png")),
    ("PRN232 SP26 FE - Câu 11", Path("data/cropped/PRN232/exam_193/q011.png")),
    ("PRN232 SP26 FE - Câu 29", Path("data/cropped/PRN232/exam_193/q029.png")),
]

system_prompt = (
    "You are an expert exam analyzer. Analyze the exam question image carefully.\n"
    "Identify the question stem and the options (A, B, C, D).\n"
    "Select the single best answer.\n"
    "Return JSON format:\n"
    '{"answers": ["X"], "confidence": 0.95, "explanation": "Detailed concise explanation in Vietnamese"}'
)
prompt = "Determine the correct answer (A, B, C, or D). Return strictly valid JSON."

print(f"=== TESTING GEMINI FLASH LITE ({provider.model}) ON 3 REAL QUESTIONS ===\n")

results = []
for label, img_path in questions_to_test:
    assert img_path.exists(), f"Image {img_path} does not exist"
    t0 = time.time()
    raw_resp = provider.call_vision_api(img_path, prompt, system_prompt)
    elapsed = time.time() - t0
    try:
        clean_text = raw_resp.strip()
        if clean_text.startswith("```json"):
            clean_text = clean_text[7:]
        if clean_text.startswith("```"):
            clean_text = clean_text[3:]
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3]
        parsed = json.loads(clean_text.strip())
    except Exception as e:
        parsed = {"raw": raw_resp, "error": str(e)}

    res_item = {
        "label": label,
        "image": str(img_path),
        "elapsed_seconds": round(elapsed, 2),
        "response": parsed,
    }
    results.append(res_item)
    print(f"[{label}] ({elapsed:.2f}s)")
    print(f"  Answers: {parsed.get('answers')}")
    print(f"  Confidence: {parsed.get('confidence')}")
    print(f"  Explanation: {parsed.get('explanation')}\n")

with open("data/cache/gemini_lite_test_results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print("Saved report to data/cache/gemini_lite_test_results.json")
