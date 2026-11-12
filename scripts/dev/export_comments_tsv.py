from pathlib import Path
import sqlite3

def export_comments_tsv():
    db_path = Path("data/gomde.db")
    export_dir = Path("data/exports")
    export_dir.mkdir(parents=True, exist_ok=True)
    tsv_path = export_dir / "comments_CSD202.tsv"

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    query = """
    SELECT q.[index], c.comment_id, c.author_hash, c.upvotes, c.quoted_comment_id, c.raw_text
    FROM comments c
    JOIN questions q ON c.question_id = q.id
    WHERE q.exam_id = 1
    ORDER BY q.[index] ASC, c.id ASC
    """

    rows = cursor.execute(query).fetchall()
    print(f"Exporting {len(rows)} comments to {tsv_path}...")

    header = ["q_index", "comment_id", "author_hash", "reactions", "quoted_comment_id", "raw_text"]

    with open(tsv_path, "w", encoding="utf-8") as f:
        f.write("\t".join(header) + "\n")
        for q_index, comment_id, author_hash, upvotes, quoted_comment_id, raw_text in rows:
            # First 6 chars of author_hash
            short_hash = (author_hash or "")[:6]
            cid = str(comment_id or "")
            rx = str(upvotes if upvotes is not None else 0)
            qid = str(quoted_comment_id or "")
            # Clean raw_text: replace tabs and newlines with space to keep TSV format clean
            clean_text = (raw_text or "").replace("\t", " ").replace("\r\n", " ").replace("\n", " ").strip()

            line = f"{q_index}\t{cid}\t{short_hash}\t{rx}\t{qid}\t{clean_text}\n"
            f.write(line)

    print(f"Export completed! File size: {tsv_path.stat().st_size} bytes, lines: {len(rows) + 1}")
    conn.close()

if __name__ == "__main__":
    export_comments_tsv()

