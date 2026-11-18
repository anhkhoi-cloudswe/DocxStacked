import urllib.request
import json

req = urllib.request.Request('http://127.0.0.1:8000/api/subjects/PRN232/exams')
with urllib.request.urlopen(req) as resp:
    data = json.loads(resp.read().decode())
    print(f'Total exams returned: {len(data)}')
    for ex in data:
        t = ex.get('title')
        etype = ex.get('exam_type')
        term = ex.get('term')
        compiled = ex.get('compiled')
        has_file = ex.get('has_file')
        fsize = ex.get('file_size_bytes')
        url = ex.get('url')
        print(f"ID={ex.get('id')} | {t} | type={etype} | term={term} | compiled={compiled} | has_file={has_file} | size={fsize} | url={url}")
