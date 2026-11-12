import json

with open('C:/Users/Admin/.gemini/antigravity/brain/54d3977f-6db8-412b-9d5f-bb38fade0d94/.system_generated/logs/transcript_full.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        if 'MLN122' in line:
            data = json.loads(line)
            content = data.get('content', '')
            for l in content.split('\n'):
                if 'MLN122' in l or 'PRN232' in l:
                    print(f"Step {data.get('step_index')}: {l[:120]}")

