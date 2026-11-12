"""
scripts/reference/fe_reference.py
Reference standalone script for FE exam processing:
  1. Image cropping (masks title bar and watermark).
  2. Comment parsing (handles '? [A-D]', multi-choice, agreements, explicit answers).
  3. Voting algorithm (one author_hash one vote, reaction weights, conflict detection).
  4. Word document generation (Letter size, 20pt bold red answers, teacher style).
"""

import math
import re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from PIL import Image, ImageDraw


# --- 1. Image Cropping ---

def crop_question(image_path: Path, output_path: Optional[Path] = None, margin: int = 12) -> Image.Image:
    with Image.open(image_path) as raw:
        im = raw.convert("RGB")
        w, h = im.size

        # Mask top title bar (y: 0..36) and watermark (x: 0..180, y: 630..h)
        masked = im.copy()
        draw = ImageDraw.Draw(masked)
        draw.rectangle([0, 0, w, 36], fill=(255, 255, 255))
        draw.rectangle([0, 630, 180, h], fill=(255, 255, 255))
        draw.rectangle([0, 0, 2, h], fill=(255, 255, 255))
        draw.rectangle([w - 2, 0, w, h], fill=(255, 255, 255))
        draw.rectangle([0, h - 2, w, h], fill=(255, 255, 255))

        pixels = masked.load()
        min_x, min_y, max_x, max_y = w, h, 0, 0
        found = False

        for y in range(h):
            for x in range(w):
                r, g, b = pixels[x, y]
                if r < 240 or g < 240 or b < 240:
                    found = True
                    if x < min_x: min_x = x
                    if x > max_x: max_x = x
                    if y < min_y: min_y = y
                    if y > max_y: max_y = y

        if not found or (max_x - min_x) < 150 or (max_y - min_y) < 40:
            if output_path:
                im.save(output_path, "PNG")
            return im

        x1 = max(0, min_x - margin)
        y1 = max(0, min_y - margin)
        x2 = min(w, max_x + margin)
        y2 = min(h, max_y + margin)

        cropped = im.crop((x1, y1, x2, y2))
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            cropped.save(output_path, "PNG")
        return cropped


# --- 2. Comment Parser ---

def parse_comment(text: str) -> Tuple[List[str], bool, bool]:
    """
    Returns: (answers_list, is_agreement, is_ambiguous)
    Handles:
      - '? [A-D]' (e.g. 'câu hỏi là gì? A')
      - Single letter ('b', 'B')
      - Prefix ('đáp án C', 'chọn B', 'ans: D')
      - Multi-choice ('A, C', 'a và c', 'AC', 'abd')
      - Agreement ('+1', 'chuẩn', 'đúng', 'ok')
      - Ambiguous ('có đúng A không?', 'ai biết đáp án không')
    """
    t = text.strip()
    if not t:
        return [], False, True

    lower = t.lower()

    if re.search(r"\b(ai biết|là gì thế|đúng không|phải không)\b", lower):
        if not re.search(r"\?\s*[A-D]\b", t):
            return [], False, True

    if re.fullmatch(r"\+1(\s+.*)?", lower) or re.fullmatch(r"(chuẩn|chuan|đúng|dung|ok|đồng ý|chính xác)(\s+(luôn|rồi|nhe|nhé|nha|ạ|bác|ad|bạn))?[.!]*", lower):
        return [], True, False

    # Question mark followed by letter at end (câu hỏi? A)
    m_q = re.search(r"\?\s*([A-D])\s*$", t, re.IGNORECASE)
    if m_q:
        return [m_q.group(1).upper()], False, False

    # Correction: không phải A, là B
    m_cor = re.search(r"(?:không phải|k phải)\s+[A-D][,\s]+(?:là|đáp án là)\s+([A-D])\b", lower, re.IGNORECASE)
    if m_cor:
        return [m_cor.group(1).upper()], False, False

    # Exact single letter
    if re.fullmatch(r"[A-D]", t, re.IGNORECASE):
        return [t.upper()], False, False

    # Explicit: đáp án C, chọn B, ans: D
    m_exp = re.search(r"\b(?:đáp án|dap an|chọn|chon|ans|answer)[:\s]+([A-D])\b", t, re.IGNORECASE)
    if m_exp:
        return [m_exp.group(1).upper()], False, False

    # Conversational: mình nghĩ đáp án c nhé, B là chuẩn giáo trình, A đúng
    m_think = re.search(r"\b(?:nghĩ|nghi|đoán|chắc)(?:\s+là|\s+đáp án)?\s+([A-D])\b", t, re.IGNORECASE)
    if m_think:
        return [m_think.group(1).upper()], False, False

    m_conf = re.search(r"\b([A-D])\s+(?:là\s+chuẩn|đúng|chuẩn|chính xác)\b", t, re.IGNORECASE)
    if m_conf:
        return [m_conf.group(1).upper()], False, False

    # Multi-choice with separators: A, C or a và c or A + D
    m_multi = re.findall(r"\b([A-D])\b", t, re.IGNORECASE)
    if len(m_multi) >= 2 and re.search(r"[A-D]\s*(?:,|và|\+|&|/|\s)\s*[A-D]", t, re.IGNORECASE):
        return sorted(list(set(l.upper() for l in m_multi))), False, False

    # Ascending concatenated: AC, ABD
    m_cat = re.fullmatch(r"([a-dA-D]{2,4})", t)
    if m_cat:
        w = m_cat.group(1).upper()
        letters = list(w)
        if letters == sorted(letters) and len(letters) == len(set(letters)):
            return letters, False, False

    return [], False, True


# --- 3. Voting Algorithm ---

def tally_votes(comments: List[dict], ai_vote: Optional[List[str]] = None) -> dict:
    """
    Each author_hash only gets 1 vote (newest valid comment).
    Weights: 1 + log2(1 + reactions), agreements get half weight of parent.
    """
    if not comments and not ai_vote:
        return {"answer_set": ["?"], "status": "no_data", "confidence": 0.0}

    # Group by author_hash (take first encountered = newest)
    seen_authors: Set[str] = set()
    contributions = []

    cmt_by_id = {str(c.get("comment_id")): c for c in comments if c.get("comment_id")}

    for c in comments:
        author = c.get("author_hash", "anon")
        if author in seen_authors:
            continue

        raw = c.get("raw_text", "")
        answers, is_agree, is_ambig = parse_comment(raw)

        if is_ambig and not is_agree:
            continue

        rx = c.get("reactions", 0) or 0
        if is_agree and c.get("quoted_comment_id"):
            parent = cmt_by_id.get(str(c["quoted_comment_id"]))
            if parent:
                p_ans, _, _ = parse_comment(parent.get("raw_text", ""))
                if p_ans:
                    weight = round((1.0 + math.log2(1.0 + (parent.get("reactions", 0) or 0))) * 0.5, 3)
                    seen_authors.add(author)
                    contributions.append({"author": author, "answers": p_ans, "weight": weight})
        elif answers:
            weight = round(1.0 + math.log2(1.0 + rx), 3)
            seen_authors.add(author)
            contributions.append({"author": author, "answers": answers, "weight": weight})

    if ai_vote:
        contributions.append({"author": "ai", "answers": [a.upper() for a in ai_vote], "weight": 1.0})

    if not contributions:
        return {"answer_set": ["?"], "status": "no_data", "confidence": 0.0}

    # Tally
    total_w = sum(c["weight"] for c in contributions)
    opt_w: Dict[str, float] = {}
    opt_voters: Dict[str, Set[str]] = {}
    for c in contributions:
        for a in c["answers"]:
            opt_w[a] = opt_w.get(a, 0.0) + c["weight"]
            if a not in opt_voters:
                opt_voters[a] = set()
            opt_voters[a].add(c["author"])

    sorted_opts = sorted(opt_w.items(), key=lambda x: x[1], reverse=True)
    winner = sorted_opts[0][0]
    conf = round(sorted_opts[0][1] / max(total_w, 1.0), 3)

    conflict = False
    if len(sorted_opts) >= 2:
        opt1, opt2 = sorted_opts[0][0], sorted_opts[1][0]
        # Equal voters count -> CONFLICT
        if len(opt_voters.get(opt1, set())) == len(opt_voters.get(opt2, set())):
            conflict = True
        else:
            margin = (sorted_opts[0][1] - sorted_opts[1][1]) / max(total_w, 1.0)
            if margin < 0.15:
                conflict = True

    winner_voters_count = len(opt_voters.get(winner, set()))

    if conflict:
        status = "conflict"
    elif conf >= 0.70 and winner_voters_count >= 2:
        status = "confident"
    else:
        status = "weak"

    return {
        "answer_set": [winner],
        "status": status,
        "confidence": conf,
        "vote_breakdown": opt_w,
        "total_weight": total_w,
        "voters_count": len(contributions),
    }

