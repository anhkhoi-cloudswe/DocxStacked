import json

with open('C:/Users/Admin/.gemini/antigravity/brain/54d3977f-6db8-412b-9d5f-bb38fade0d94/.system_generated/logs/transcript_full.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        data = json.loads(line)
        if data.get('step_index') == 870:
            content = data.get('content', '')
            # find if there is python code
            if 'def ' in content or 'import ' in content:
                print("Found code in step 870!")
            else:
                print("No code in step 870. Content was PLAN_BUOC3_FE_DOCX.md text.")
        if data.get('step_index') == 1277:
            print("Step 1277 content:")
            print(data.get('content'))

