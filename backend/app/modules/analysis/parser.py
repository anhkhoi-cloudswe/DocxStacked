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


def parse_comment_text(
    raw_text: str,
    max_option_letter: str = "H",
    multi_choice_n: Optional[int] = None,
) -> ParsedComment:
    """
    Parse student comment text to extract voted answer(s) using structural rules.
    Configurable:
      - max_option_letter: upper bound on valid option letters (default 'H'). Letters beyond this are discarded.
      - multi_choice_n: expected number of answers for multi-choice questions.

    Structural Rules:
      1. Pure standalone letter: accepted ONLY when the entire comment is essentially just that letter
         (e.g. 'e', 'E', 'B.', 'a:') OR preceded by an explicit keyword ('đáp án', 'chọn', 'ans', 'câu này').
         Conversational words like 'e' in 'e nghĩ là B' or 'a' in 'a ơi' are rejected; only 'B' is parsed.
      2. Concatenated letter words ('ae', 'be', 'de', 'ad', 'ace'):
         Accepted ONLY when question is multiple choice AND len(word) == multi_choice_n.
         Otherwise, ambiguous / discarded to prevent Vietnamese false positives.
      3. Negative correction: 'không phải A, là B' -> ['B'].
      4. Clarified statements: 'nghĩ là B' -> ['B'], 'B là chuẩn' -> ['B'].
      5. Multi-choice with separators: 'A, C', 'a và e', 'A + E', 'B, E'.
    """
    cleaned = normalize_vietnamese_text(raw_text)
    if not cleaned:
        return ParsedComment(raw_text=raw_text, is_ambiguous=True)

    max_char = max_option_letter.upper()
    valid_pattern = f"[A-{max_char}]"

    def filter_letters(letters: List[str]) -> List[str]:
        return [l.upper() for l in letters if l.upper() <= max_char]

    lower = cleaned.lower()

    # 1. Check ambiguous / question marks that indicate student is unsure or asking
    # e.g. "có đúng A không?", "ai biết đáp án không", "đáp án là gì thế", "A hay B"
    if re.search(r"\b(ai biết|là gì thế|đáp án gì|chắc không|đúng không|phải không)\b", lower):
        if not re.search(rf"\?\s*{valid_pattern}\b", cleaned, re.IGNORECASE):
            return ParsedComment(raw_text=raw_text, is_ambiguous=True)

    if re.search(rf"có\s+đúng\s+{valid_pattern}\s+không\??", lower, re.IGNORECASE):
        return ParsedComment(raw_text=raw_text, is_ambiguous=True)

    # 2. Check agreement (+1, đúng rồi, chuẩn luôn, ok)
    if re.fullmatch(r"\+1(\s+.*)?", lower) or re.fullmatch(r"(chuẩn|chuan|đúng|dung|ok|đồng ý|chính xác)(\s+(luôn|rồi|nhe|nhé|nha|ạ|bác|ad|bạn))?[.!]*", lower):
        return ParsedComment(raw_text=raw_text, is_agreement=True)

    # 3. Check pattern: '...câu hỏi? [A-Z]' (e.g. 'Tính ổn định của thuật toán Merge Sort là gì? A')
    m_qmark = re.search(rf"\?\s*({valid_pattern})\s*$", cleaned, re.IGNORECASE)
    if m_qmark:
        letter = m_qmark.group(1).upper()
        return ParsedComment(raw_text=raw_text, answers=[letter])

    # 4. Check negative correction: 'không phải A, là B' or 'sai rồi, đáp án là B'
    m_correction = re.search(rf"(?:không phải|k phải|ko phải)\s+{valid_pattern}[,\s]+(?:là|mà là|đáp án là)\s+({valid_pattern})\b", lower, re.IGNORECASE)
    if m_correction:
        letter = m_correction.group(1).upper()
        return ParsedComment(raw_text=raw_text, answers=[letter])

    # 5. Check pure standalone exact letter: 'b', 'B', '  c  ', 'e', 'E', 'A.', 'e.'
    # Student comment is ONLY this letter (with optional dot/colon)
    m_single = re.fullmatch(rf"({valid_pattern})[.:]?", cleaned, re.IGNORECASE)
    if m_single:
        return ParsedComment(raw_text=raw_text, answers=[m_single.group(1).upper()])

    # 6. Check explicit prefix/suffix patterns:
    # 'đáp án C', 'dap an C', 'chọn B', 'chon B', 'ans: D', 'answer: E', 'câu này E'
    m_explicit = re.search(rf"\b(?:đáp án|dap an|chọn|chon|ans|answer|câu này|cau nay|câu|cau)[:\s]+({valid_pattern})\b", cleaned, re.IGNORECASE)
    if m_explicit:
        return ParsedComment(raw_text=raw_text, answers=[m_explicit.group(1).upper()])

    # 7. Check conversational statement with thinking keywords:
    # 'mình nghĩ đáp án c nhé', 'nghĩ là B', 'chắc là A', 'nghĩ là E', 'e nghĩ là B' -> 'B'
    m_think = re.search(rf"\b(?:nghĩ|nghi|đoán|doan|chắc|chac)(?:\s+là|\s+đáp án)?\s+({valid_pattern})\b", cleaned, re.IGNORECASE)
    if m_think:
        return ParsedComment(raw_text=raw_text, answers=[m_think.group(1).upper()])

    # 8. Check confirmation statement:
    # 'B là chuẩn giáo trình', 'A đúng', 'B chuẩn', 'E chính xác'
    m_confirm = re.search(rf"\b({valid_pattern})\s+(?:là\s+chuẩn|đúng|dung|chuẩn|chuan|chính xác|chinh xac)\b", cleaned, re.IGNORECASE)
    if m_confirm:
        return ParsedComment(raw_text=raw_text, answers=[m_confirm.group(1).upper()])

    # 9. Multi-choice with explicit separators:
    # 'A, C', 'B, E', 'a và e', 'A + C', 'A & C', 'A / C'
    # Check if string has letters separated by delimiters
    sep_pattern = rf"({valid_pattern})\s*(?:,|và|\+|&|/|\s)\s*({valid_pattern})"
    if re.search(sep_pattern, cleaned, re.IGNORECASE):
        # Extract individual separated letters
        all_tokens = re.findall(rf"\b({valid_pattern})\b", cleaned, re.IGNORECASE)
        filtered = filter_letters(all_tokens)
        if len(filtered) >= 2:
            words = cleaned.split()
            # If <= 6 words total or starts with keyword + answers
            if len(words) <= 6 or re.search(rf"^(?:đáp án|chọn|ans)?\s*{valid_pattern}(?:\s*(?:,|và|\+|&|/)\s*{valid_pattern})+", cleaned, re.IGNORECASE):
                letters = sorted(list(set(filtered)))
                return ParsedComment(raw_text=raw_text, answers=letters)

    # 10. Concatenated letters: 'AC', 'ABD', 'abd', 'BCDE', 'ae', 'be', 'de', 'ad', 'ABE'
    # Rule 2: Chuỗi liền chỉ nhận khi câu đó là nhiều đáp án và số chữ cái đúng bằng N.
    m_concat = re.fullmatch(r"([a-zA-Z]{2,6})", cleaned)
    if m_concat:
        word = m_concat.group(1).upper()
        letters = list(word)
        # Check all letters in valid range
        if all(l <= max_char for l in letters):
            # Must strictly match multi_choice_n if specified!
            if multi_choice_n is not None and multi_choice_n >= 2:
                if len(letters) == multi_choice_n and len(letters) == len(set(letters)):
                    # Strictly ascending or exact set
                    return ParsedComment(raw_text=raw_text, answers=sorted(letters))
                else:
                    return ParsedComment(raw_text=raw_text, is_ambiguous=True)
            else:
                # If multi_choice_n is not specified, concatenated words that look like Vietnamese
                # e.g. 'ae' (anh em), 'be' (bé), 'de' (dễ), 'ad' (admin) MUST NOT be recognized as answers!
                return ParsedComment(raw_text=raw_text, is_ambiguous=True)

    # 11. Final trailing letter check if comment is an explanation ending with answer
    # e.g. "B D sai vì trong giáo trình... nên chọn E"
    m_end_choice = re.search(rf"(?:nên chọn|chon|đáp án là|chọn)\s+({valid_pattern})[.\s]*$", cleaned, re.IGNORECASE)
    if m_end_choice:
        return ParsedComment(raw_text=raw_text, answers=[m_end_choice.group(1).upper()])

    return ParsedComment(raw_text=raw_text, is_ambiguous=True)

