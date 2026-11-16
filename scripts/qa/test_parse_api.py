import urllib.request
import json

sample_html = """
<div class="structItemContainer">
    <div class="structItem structItem--thread">
        <span class="label label--accent">RE</span>
        <div class="structItem-title">
            <a href="/threads/mln122-su26-re.7207/">MLN122 - Đề thi thử SU26 RE (60 câu)</a>
        </div>
        <div class="structItem-startDate">
            <time datetime="2026-08-01T20:00:00+0700">1 Th08 2026</time>
        </div>
    </div>
</div>
"""
data = json.dumps({'html': sample_html, 'subject_code': 'MLN122'}).encode('utf-8')
req = urllib.request.Request('http://127.0.0.1:8000/api/subjects/parse-forum-html', data=data, headers={'Content-Type': 'application/json'})
with urllib.request.urlopen(req) as r:
    print(r.read().decode('utf-8'))
