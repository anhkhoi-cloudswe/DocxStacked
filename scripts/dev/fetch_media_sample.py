import re
import urllib.request
import ssl
from pathlib import Path
from bs4 import BeautifulSoup

url = "https://fuoverflow.com/media/q1-webp.134314/"
print(f"Fetching sample media item (question 1): {url}")

ctx = ssl.create_default_context()
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

req = urllib.request.Request(url, headers=headers)
try:
    with urllib.request.urlopen(req, context=ctx, timeout=15) as res:
        print(f"Status: {res.status}")
        print(f"Final URL: {res.geturl()}")
        content = res.read().decode("utf-8", errors="ignore")
        
        # Save fixture
        fixture_path = Path("data/fixtures/sample_media_q1_comments.html")
        fixture_path.write_text(content, encoding="utf-8")
        print(f"Saved fixture to {fixture_path}")
        
        soup = BeautifulSoup(content, "html.parser")
        
        # Title
        print("Page Title:", soup.title.string if soup.title else "")
        
        # High-res image in media view
        media_img = soup.select_one(".xfmgMediaView-image img, .media-image img, .imageContainer img")
        if media_img:
            print("Media Image src:", media_img.get("src"))
        else:
            # Look for any large image
            all_imgs = soup.find_all("img")
            print(f"Total images on media page: {len(all_imgs)}")
            for im in all_imgs[:5]:
                print("  img:", im.get("src"))

        # Comments
        # In XFMG, comments are usually .message--mediaComment or .comment or .xfmgComment
        comments = soup.select(".message--mediaComment, .xfmgComment, .comment, .message[data-content]")
        print(f"\nComments found by selectors: {len(comments)}")
        
        # If not found by specific selectors, search for comment containers
        comment_list = soup.select(".message-responseRow, .commentList .comment, article.message")
        print(f"Alternative comment elements found: {len(comment_list)}")
        
        for idx, c in enumerate(comments or comment_list):
            author = c.select_one(".message-name, .comment-user, .username")
            author_text = author.get_text(strip=True) if author else "Unknown"
            
            body = c.select_one(".message-body, .comment-content, .bbWrapper")
            body_text = body.get_text(strip=True) if body else ""
            
            reactions = c.select_one(".reactionsBar, .comment-reactions, .reaction")
            react_text = reactions.get_text(strip=True) if reactions else "0 votes"
            
            time_el = c.select_one("time, .u-dt")
            time_text = time_el.get_text(strip=True) if time_el else ""
            
            print(f"\n  [Comment #{idx+1}] Author: {author_text} | Time: {time_text} | Votes: {react_text}")
            print(f"    Body: {body_text}")

except Exception as e:
    print(f"Error fetching media comments: {e}")

