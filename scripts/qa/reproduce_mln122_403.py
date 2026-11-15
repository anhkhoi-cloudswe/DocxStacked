import json
import os
from pathlib import Path
import sys
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

def test_urls():
    urls = [
        ("MLN122 Q1", "https://fuoverflow.com/media/q1-webp.137152/"),
        ("ITE302c Q1", "https://fuoverflow.com/media/q1-webp.139767/"),
    ]
    
    profile_dir = Path("data/browser_profile").resolve()
    
    print("=" * 90)
    print("TASK 3 FORENSIC: REPRODUCING MLN122 (137152) & ITE302c (139767) MEDIA URLS")
    print("=" * 90)
    
    with sync_playwright() as pw:
        # A. Authenticated persistent browser context
        print("\n--- [PART A: AUTHENTICATED BROWSER CONTEXT (data/browser_profile)] ---")
        try:
            ctx_auth = pw.chromium.launch_persistent_context(
                str(profile_dir),
                channel="chrome",
                headless=True,
            )
            for label, url in urls:
                print(f"\nTarget: {label} -> {url}")
                resp = ctx_auth.request.get(url, timeout=20000)
                status = resp.status
                text = resp.text()
                soup = BeautifulSoup(text, "html.parser")
                title = soup.title.string.strip() if soup.title else "<no title>"
                is_logged_in = 'data-logged-in="true"' in text
                template = soup.html.get("data-template", "<no template>") if soup.html else "<no html>"
                
                # Check for XenForo permission error blocks
                error_block = soup.select_one(".blockMessage--error, .p-body-pageContent .block--messages")
                error_text = error_block.get_text(strip=True) if error_block else "None"
                
                print(f"Status Code : {status}")
                print(f"Title       : {title}")
                print(f"Template    : {template}")
                print(f"Logged-in   : {is_logged_in}")
                print(f"XenForo Err : {error_text}")
                print(f"Body (First 500 chars):\n{text[:500]}")
                print("-" * 50)
            ctx_auth.close()
        except Exception as e:
            print(f"Error launching authenticated context: {e}")

        # B. Unauthenticated clean browser context
        print("\n--- [PART B: UNAUTHENTICATED BROWSER CONTEXT (no cookies / fresh)] ---")
        try:
            browser = pw.chromium.launch(headless=True)
            ctx_clean = browser.new_context()
            for label, url in urls:
                print(f"\nTarget: {label} -> {url}")
                resp = ctx_clean.request.get(url, timeout=20000)
                status = resp.status
                text = resp.text()
                soup = BeautifulSoup(text, "html.parser")
                title = soup.title.string.strip() if soup.title else "<no title>"
                is_logged_in = 'data-logged-in="true"' in text
                template = soup.html.get("data-template", "<no template>") if soup.html else "<no html>"
                
                error_block = soup.select_one(".blockMessage--error, .p-body-pageContent .block--messages")
                error_text = error_block.get_text(strip=True) if error_block else "None"
                
                print(f"Status Code : {status}")
                print(f"Title       : {title}")
                print(f"Template    : {template}")
                print(f"Logged-in   : {is_logged_in}")
                print(f"XenForo Err : {error_text}")
                print(f"Body (First 500 chars):\n{text[:500]}")
                print("-" * 50)
            browser.close()
        except Exception as e:
            print(f"Error launching clean context: {e}")

if __name__ == "__main__":
    test_urls()
