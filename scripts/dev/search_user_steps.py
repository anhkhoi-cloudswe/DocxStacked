import json

with open('C:/Users/Admin/.gemini/antigravity/brain/54d3977f-6db8-412b-9d5f-bb38fade0d94/.system_generated/logs/transcript_full.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        data = json.loads(line)
        if data.get('source') == 'USER_EXPLICIT':
            c = data.get('content', '')
            if 'fe_reference' in c or 'def parse' in c or 'crop_question' in c or 'vote' in c:
                print(f"User Step {data.get('step_index')}: len={len(c)}")
                for l in c.split('\n')[:8]:
                    print('  ', l)

