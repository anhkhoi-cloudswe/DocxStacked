import json

with open('C:/Users/Admin/.gemini/antigravity/brain/54d3977f-6db8-412b-9d5f-bb38fade0d94/.system_generated/logs/transcript_full.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        data = json.loads(line)
        if data.get('step_index') in range(903, 915):
            print(f"Step {data.get('step_index')}: {data.get('content')[:200] if data.get('content') else ''}")

