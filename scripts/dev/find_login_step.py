from pathlib import Path
import json

transcript_path = Path("C:/Users/Admin/.gemini/antigravity/brain/54d3977f-6db8-412b-9d5f-bb38fade0d94/.system_generated/logs/transcript_full.jsonl")
with open(transcript_path, "r", encoding="utf-8") as f:
    for line in f:
        data = json.loads(line)
        content = data.get("content", "")
        if "login" in content.lower() and ("dong khoi" in content.lower() or "đông khởi" in content.lower() or "anhkhoi" in content.lower()):
            print(f"Step {data.get('step_index')}: {content[:200]}")

