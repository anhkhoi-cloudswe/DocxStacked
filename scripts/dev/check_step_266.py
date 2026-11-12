from pathlib import Path
import json

transcript_path = Path("C:/Users/Admin/.gemini/antigravity/brain/54d3977f-6db8-412b-9d5f-bb38fade0d94/.system_generated/logs/transcript_full.jsonl")
with open(transcript_path, "r", encoding="utf-8") as f:
    for line in f:
        data = json.loads(line)
        if data.get("step_index") == 266:
            print("Step 266 content:")
            print(data.get("content"))

