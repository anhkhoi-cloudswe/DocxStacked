import re
from typing import List, Optional, Set
from pydantic import BaseModel


class ParsedComment(BaseModel):
    raw_text: str
    answers: List[str] = []
    is_agreement: bool = False
    is_ambiguous: bool = False
    explanation: Optional[str] = None


def normalize_vietnamese_text(text: str) -> str:
    """Normalize Vietnamese text for matching (lowercase, clean whitespace)."""
    text = text.strip()
    return re.sub(r"\s+", " ", text)


def parse_comment_text(raw_text: str) -> ParsedComment:
    """
    Parse student comment text to extract voted answer(s).
    Rules:
      1. Question mark followed by letter: '...là gì? A' -> ['A']
      2. Direct single letter: 'b', 'B' -> ['B']
      3. Explicit answers: 'đáp án C', 'dap an c', 'chọn B', 'ans: D' -> ['C'], ['B'], ['D']
      4. Clarified answers: 'B là chuẩn giáo trình', 'A đúng', 'không phải A, là B' -> ['B']
      5. Multi-choice: 'A, C', 'a và c', 'AC', 'A + D', 'abd' (ascending concatenated)
      6. Agreement: '+1', 'đúng', 'chuẩn', 'ok' -> is_agreement=True
      7. Ambiguous/questioning: 'có đúng A không?', 'ai biết đáp án không' -> is_ambiguous=True
    """
    cleaned = normalize_vietnamese_text(raw_text)
    if not cleaned:
        return ParsedComment(raw_text=raw_text, is_ambiguous=True)

    lower = cleaned.lower()

    # 1. Check ambiguous / question marks that indicate student is unsure or asking
    # e.g. "có đúng A không?", "ai biết đáp án không", "đáp án là gì thế", "A hay B"
    if re.search(r"\b(ai biết|là gì thế|đáp án gì|chắc không|đúng không|phải không)\b", lower):
        if not re.search(r"\?\s*[A-D]\b", cleaned):
            return ParsedComment(raw_text=raw_text, is_ambiguous=True)

    if re.search(r"có\s+đúng\s+[A-D]\s+không\??", lower, re.IGNORECASE):
        return ParsedComment(raw_text=raw_text, is_ambiguous=True)

    # 2. Check agreement (+1, đúng rồi, chuẩn luôn, ok)
    if re.fullmatch(r"\+1(\s+.*)?", lower) or re.fullmatch(r"(chuẩn|chuan|đúng|dung|ok|đồng ý|chính xác)(\s+(luôn|rồi|nhe|nhé|nha|ạ|bác|ad|bạn))?[.!]*", lower):
        return ParsedComment(raw_text=raw_text, is_agreement=True)

    # 3. Check pattern: '...câu hỏi? [A-D]' (e.g. 'Tính ổn định của thuật toán Merge Sort là gì? A')
    # Or '... ? [A-D]'
    m_qmark = re.search(r"\?\s*([A-D])\s*$", cleaned, re.IGNORECASE)
    if m_qmark:
        letter = m_qmark.group(1).upper()
        return ParsedComment(raw_text=raw_text, answers=[letter])

    # 4. Check negative correction: 'không phải A, là B' or 'sai rồi, đáp án là B'
    m_correction = re.search(r"(?:không phải|k phải|ko phải)\s+[A-D][,\s]+(?:là|mà là|đáp án là)\s+([A-D])\b", lower, re.IGNORECASE)
    if m_correction:
        letter = m_correction.group(1).upper()
        return ParsedComment(raw_text=raw_text, answers=[letter])

    # 5. Check single exact letter: 'b', 'B', '  c  '
    if re.fullmatch(r"[A-D]", cleaned, re.IGNORECASE):
        return ParsedComment(raw_text=raw_text, answers=[cleaned.upper()])

    # 6. Check explicit prefix/suffix patterns:
    # 'đáp án C', 'dap an C', 'chọn B', 'chon B', 'ans: D', 'answer: D'
    m_explicit = re.search(r"\b(?:đáp án|dap an|chọn|chon|ans|answer|câu|cau)[:\s]+([A-D])\b", cleaned, re.IGNORECASE)
    if m_explicit:
        return ParsedComment(raw_text=raw_text, answers=[m_explicit.group(1).upper()])

    # 7. Check conversational statement:
    # 'mình nghĩ đáp án c nhé', 'nghĩ là B', 'chắc là A'
    m_think = re.search(r"\b(?:nghĩ|nghi|đoán|doan|chắc|chac)(?:\s+là|\s+đáp án)?\s+([A-D])\b", cleaned, re.IGNORECASE)
    if m_think:
        return ParsedComment(raw_text=raw_text, answers=[m_think.group(1).upper()])

    # 8. Check confirmation statement:
    # 'B là chuẩn giáo trình', 'A đúng', 'B chuẩn', 'C chính xác'
    m_confirm = re.search(r"\b([A-D])\s+(?:là\s+chuẩn|đúng|dung|chuẩn|chuan|chính xác|chinh xac)\b", cleaned, re.IGNORECASE)
    if m_confirm:
        return ParsedComment(raw_text=raw_text, answers=[m_confirm.group(1).upper()])

    # 9. Multi-choice:
    # A, C or A và C or A + C or A & C
    m_multi_sep = re.findall(r"\b([A-D])\b", cleaned, re.IGNORECASE)
    if len(m_multi_sep) >= 2:
        # Check if they are separated by delimiters like , + / và and
        # e.g. "A, C", "a và c", "A + D", "A / D"
        if re.search(r"[A-D]\s*(?:,|và|\+|&|/|\s)\s*[A-D]", cleaned, re.IGNORECASE):
            letters = sorted(list(set(l.upper() for l in m_multi_sep)))
            return ParsedComment(raw_text=raw_text, answers=letters)

    # 10. Concatenated ascending letters: 'AC', 'ABD', 'abd'
    # Must be 2-4 uppercase/lowercase letters strictly ascending alphabetically (to avoid words like 'da', 'ba')
    m_concat = re.fullmatch(r"([a-dA-D]{2,4})", cleaned)
    if m_concat:
        word = m_concat.group(1).upper()
        # Ensure strictly ascending order: A < B < C < D
        letters = list(word)
        if letters == sorted(letters) and len(letters) == len(set(letters)):
            return ParsedComment(raw_text=raw_text, answers=letters)

    # 11. Final trailing letter check if comment is an explanation ending with answer
    # e.g. "B D sai vì trong giáo trình... nên chọn C" or ends with ". B"
    m_end_choice = re.search(r"(?:nên chọn|chon|đáp án là|chọn)\s+([A-D])[.\s]*$", cleaned, re.IGNORECASE)
    if m_end_choice:
        return ParsedComment(raw_text=raw_text, answers=[m_end_choice.group(1).upper()])

    return ParsedComment(raw_text=raw_text, is_ambiguous=True)

