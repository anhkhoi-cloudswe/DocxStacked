import re

def clean_comment_dom(text: str) -> str:
    # Check if this comment text contains XenForo metadata block
    # Pattern: avatar initial / username, score, date/time header
    # e.g. "H \n\t\thoofour\n -388\n 10/3/26\n d"
    # or "tamvq\n 0\n Thứ sáu lúc 13:18\n c"
    # Split by timestamp or date line:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return ""
    
    # If lines contain a date or timestamp line, comment body is after the timestamp
    time_idx = -1
    for i, ln in enumerate(lines):
        if re.search(r"(?:lúc\s+\d{1,2}:\d{2}|\b\d{1,2}\/\d{1,2}\/\d{2,4}\b)", ln, re.IGNORECASE):
            time_idx = i
            break
            
    if time_idx != -1 and time_idx + 1 < len(lines):
        body_lines = lines[time_idx + 1:]
        # also ignore trailing reaction bar / user signatures if any
        cleaned_body = " ".join(body_lines)
        return cleaned_body
    elif time_idx != -1 and time_idx + 1 == len(lines):
        # Timestamp was last line -> comment had no body!
        return ""
        
    return text

print("Test hoofour:", repr(clean_comment_dom("H \n\t\thoofour\n -388\n 10/3/26\n d")))
print("Test tamvq:", repr(clean_comment_dom("T \n\t\ttamvq\n 0\n Thứ sáu lúc 13:18\n c")))
print("Test ccc:", repr(clean_comment_dom("C \n\t\tccc\n -3\n Thứ sáu lúc 20:15")))
print("Test normal:", repr(clean_comment_dom("Đáp án D nhé mn")))
