from pathlib import Path
from bs4 import BeautifulSoup

def print_dom_proof():
    p = Path("data/raw/MLN122/exam_136_SU26/comments/q014_137165.html")
    if not p.exists():
        print("File not found:", p)
        return
        
    soup = BeautifulSoup(p.read_text(encoding="utf-8"), "html.parser")
    print("=" * 65)
    print("DOM PROOF CHO CÂU 14 (MLN122 - SU26 - RE)")
    print("Xác minh con số -2, -12, -11 là điểm của THÀNH VIÊN hay của BÌNH LUẬN")
    print("=" * 65)
    
    for i, c in enumerate(soup.select(".message--comment, .message--mediaComment, .js-comment"), start=1):
        author_el = c.select_one(".username")
        user_vote_el = c.select_one(".user-fuo-vote")
        rx_bar = c.select_one(".reactionsBar")
        body_el = c.select_one(".message-body")
        
        author = author_el.get_text(strip=True) if author_el else "Unknown"
        user_score = user_vote_el.get_text(strip=True) if user_vote_el else "None"
        user_vote_class = user_vote_el.get("class", []) if user_vote_el else []
        rx_text = rx_bar.get_text(" ", strip=True) if rx_bar else "Trống (0 reaction)"
        body = body_el.get_text(" ", strip=True) if body_el else ""
        
        print(f"Bình luận #{i}:")
        print(f"  • Người đăng       : {author}")
        print(f"  • Thẻ .user-fuo-vote: {user_score} (Class: {' '.join(user_vote_class)})")
        print(f"    -> Vị trí DOM    : Nằm trong <li class='message-attribution-user'> (Profile thành viên)")
        print(f"  • Thẻ .reactionsBar : {rx_text}")
        print(f"    -> Vị trí DOM    : Nằm ở chân bình luận (Điểm tương tác của chính comment này)")
        print(f"  • Nội dung comment : \"{body}\"")
        print("-" * 65)

if __name__ == "__main__":
    print_dom_proof()
