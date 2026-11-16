import sqlite3
import shutil
from pathlib import Path

def run_cleanup():
    conn = sqlite3.connect('data/docxstacked.db')
    c = conn.cursor()
    c.execute("UPDATE questions SET local_image_path = replace(local_image_path, '/TEST/', '/MLN122/') WHERE exam_id = 136")
    c.execute("DELETE FROM subjects WHERE code = 'TEST'")
    conn.commit()
    conn.close()

    for p in [Path('data/output/TEST'), Path('data/cropped/TEST'), Path('data/raw/TEST')]:
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
            print("Deleted directory:", p)
    f = Path('data/ingest_debug/payload_TEST_20261115_214925.json')
    if f.exists():
        f.unlink()
        print("Deleted file:", f)

    conn2 = sqlite3.connect('data/docxstacked.db')
    c2 = conn2.cursor()
    print("Subject TEST:", c2.execute("SELECT id, code, name FROM subjects WHERE code='TEST'").fetchall())
    print("Questions with /TEST/:", c2.execute("SELECT COUNT(*) FROM questions WHERE local_image_path LIKE '%/TEST/%'").fetchone()[0])
    conn2.close()

if __name__ == '__main__':
    run_cleanup()
