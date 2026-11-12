import urllib.request, ssl, re
from pathlib import Path

url = "https://fuoverflow.com/threads/prn212-su26-b5-fe.7422/"
ctx = ssl.create_default_context()
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})

with urllib.request.urlopen(req, context=ctx) as r:
    txt = r.read().decode("utf-8")
    Path("data/fixtures/sample_thread_fe_prn212.html").write_text(txt, encoding="utf-8")
    title = re.search(r"<title>(.*?)</title>", txt).group(1)
    imgs = re.findall(r'src="(https://data\.fuoverflow\.com/attachments/[^"]+)"', txt)
    media_links = re.findall(r'href="(/media/[^"]+)"', txt)
    print("Saved fixture to data/fixtures/sample_thread_fe_prn212.html")
    print("Title:", title)
    print("Attachment images count:", len(imgs))
    print("Media links count:", len(media_links))
    for m in media_links[:5]:
        print("  Media link:", m)

