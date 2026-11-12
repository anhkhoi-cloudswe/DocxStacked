from pathlib import Path
import re
from bs4 import BeautifulSoup

def inspect_fixtures():
    fixtures_dir = Path("data/fixtures/clean")
    for fp in fixtures_dir.glob("*.html"):
        soup = BeautifulSoup(fp.read_text(encoding="utf-8"), "html.parser")
        comments = soup.select(".message--comment, .message--mediaComment, .js-comment")
        print(f"\n=== {fp.name} ({len(comments)} comments) ===")
        for i, c in enumerate(comments):
            cid = c.get("data-content") or c.get("id") or ""
            # Author
            author_el = c.select_one(".message-name, .comment-user, .username")
            author = author_el.get_text(strip=True) if author_el else "Unknown"
            
            # Reactions
            rx_bar = c.select_one(".reactionsBar")
            rx_count = 0
            rx_text = ""
            if rx_bar:
                rx_text = rx_bar.get_text(" ", strip=True)
                # Count can be determined from reaction list items or text
                # e.g. "Bạn, Student_X và 3 người khác" or ".reaction-image" count
                icons = len(rx_bar.select(".reaction-image, .reaction"))
                # Also check numbers like "3 người khác"
                m_other = re.search(r"(\d+)\s+người", rx_text)
                if m_other:
                    rx_count = int(m_other.group(1)) + len(rx_bar.select(".reactionsBar-link:not(.reactionsBar-linkTotal)"))
                elif rx_text:
                    rx_count = max(icons, 1)
            
            # Quotes
            quote_block = c.select_one("blockquote, .bbCodeBlock--quote")
            quoted_id = None
            if quote_block:
                title_link = quote_block.select_one(".bbCodeBlock-title a")
                if title_link and title_link.get("href"):
                    # href like /media/comments/123456/
                    m = re.search(r"/comments/(\d+)", title_link.get("href"))
                    if m:
                        quoted_id = int(m.group(1))
            
            # Text excluding blockquote
            bb = c.select_one(".message-body .bbWrapper")
            if bb:
                # Copy so we don't mutate
                bb_copy = BeautifulSoup(str(bb), "html.parser").find()
                for qb in bb_copy.select("blockquote, .bbCodeBlock--quote"):
                    qb.decompose()
                clean_text = bb_copy.get_text(" ", strip=True)
            else:
                clean_text = ""

            print(f"[{i+1}] cid={cid} author={author} rx={rx_count} ('{rx_text}') quoted={quoted_id} | body='{clean_text}'")

if __name__ == "__main__":
    inspect_fixtures()

