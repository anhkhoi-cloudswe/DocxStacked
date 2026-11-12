import hashlib
from pathlib import Path
import re
from typing import List, Optional, Tuple
from bs4 import BeautifulSoup

def extract_comment_data_from_html(html_str: str, html_path: Optional[str] = None) -> List[dict]:
    soup = BeautifulSoup(html_str, "html.parser")
    comment_els = soup.select(".message--comment, .message--mediaComment, .js-comment")
    parsed = []

    for c in comment_els:
        # 1. Comment ID
        raw_id = c.get("data-content") or c.get("id") or ""
        m_id = re.search(r"\d+", raw_id)
        comment_id = m_id.group(0) if m_id else None

        # 2. Author and hash
        author_el = c.select_one(".message-name, .comment-user, .username, .comment-author")
        author_name = author_el.get_text(strip=True) if author_el else "Unknown"
        author_hash = hashlib.sha256(author_name.encode("utf-8")).hexdigest()[:16]

        # 3. Reactions / Upvotes
        rx_bar = c.select_one(".reactionsBar")
        upvotes = 0
        if rx_bar and ("is-active" in rx_bar.get("class", []) or rx_bar.select(".reaction-image, .reaction")):
            rx_text = rx_bar.get_text(" ", strip=True)
            # Check named bdi tags (e.g. <bdi>User1</bdi>, <bdi>User2</bdi>)
            bdis = rx_bar.select("a.reactionsBar-link bdi, .reactionsBar bdi")
            named_count = len(bdis)

            # Check for "and N others" or "và N người khác"
            m_others = re.search(r"(?:and|và)\s+(\d+)\s+(?:others|người khác)", rx_text, re.IGNORECASE)
            others_count = int(m_others.group(1)) if m_others else 0

            # Check for total number link (e.g. '3 reactions')
            m_total = re.search(r"(\d+)\s+(?:reactions|lượt thích|phản ứng)", rx_text, re.IGNORECASE)
            if m_total:
                upvotes = int(m_total.group(1))
            elif named_count > 0 or others_count > 0:
                upvotes = named_count + others_count
            else:
                # Count icons
                icons = len(rx_bar.select(".reaction-image, .reaction[data-reaction-id]"))
                upvotes = max(icons, 1)

        # 4. Quoted Comment ID & is_reply
        quoted_comment_id = None
        is_reply = False

        quote_block = c.select_one("blockquote, .bbCodeBlock--quote")
        if quote_block:
            is_reply = True
            # Extract id from quote title link: /media/comments/{id}/
            title_link = quote_block.select_one(".bbCodeBlock-title a")
            if title_link and title_link.get("href"):
                m_q = re.search(r"/comments/(\d+)", title_link.get("href"))
                if m_q:
                    quoted_comment_id = int(m_q.group(1))

        # Check reply button if quoted_comment_id not found
        if not quoted_comment_id:
            reply_btn = c.select_one("a.actionBar-action--reply, a[href*='comment?quote=']")
            if reply_btn and reply_btn.get("href"):
                m_btn = re.search(r"quote=(\d+)", reply_btn.get("href"))
                # Note: this is reply target for user, not necessarily parent unless it is reply
                pass

        # 5. Clean text: remove blockquotes
        bb = c.select_one(".message-body .bbWrapper, .message-body, .comment-content")
        raw_text = ""
        if bb:
            bb_copy = BeautifulSoup(str(bb), "html.parser").find()
            for qb in bb_copy.select("blockquote, .bbCodeBlock--quote"):
                qb.decompose()
            raw_text = bb_copy.get_text(" ", strip=True)

        parsed.append({
            "comment_id": comment_id,
            "author_hash": author_hash,
            "raw_text": raw_text,
            "upvotes": upvotes,
            "is_reply": is_reply,
            "quoted_comment_id": quoted_comment_id,
            "html_path": html_path,
        })

    return parsed

if __name__ == "__main__":
    for fp in Path("data/fixtures/clean").glob("*.html"):
        res = extract_comment_data_from_html(fp.read_text(encoding="utf-8"), str(fp))
        print(f"\n{fp.name} -> {len(res)} comments")
        for r in res[:4]:
            print(f"  ID={r['comment_id']}, upvotes={r['upvotes']}, is_reply={r['is_reply']}, quoted={r['quoted_comment_id']}, text='{r['raw_text'][:50]}'")

