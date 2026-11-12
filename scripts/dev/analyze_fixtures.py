#!/usr/bin/env python3
"""
scripts/analyze_fixtures.py - Analyze captured HTML fixtures and API logs

Reads:
- data/fixtures/*.html
- data/discovery_network.jsonl

Outputs / Updates:
- docs/site_notes.md
- backend/config/selectors.yaml
"""

import json
import re
from pathlib import Path
from urllib.parse import urlparse
import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
FIXTURES_DIR = DATA_DIR / "fixtures"
NETWORK_LOG_PATH = DATA_DIR / "discovery_network.jsonl"
SELECTORS_PATH = BASE_DIR / "backend" / "config" / "selectors.yaml"
NOTES_PATH = BASE_DIR / "docs" / "site_notes.md"


def main():
    print("=" * 65)
    print("  Gomde Fixture & Network Analyzer")
    print("=" * 65)

    html_files = sorted(FIXTURES_DIR.glob("*.html"))
    if not html_files:
        print("[Notice] No HTML fixtures found in data/fixtures/ yet.")
        print("Please run `discover.bat` or `python scripts/discover.py` first to capture pages.")
        return

    print(f"Found {len(html_files)} fixture(s) in {FIXTURES_DIR.relative_to(BASE_DIR)}:")
    for f in html_files:
        print(f"  - {f.name}")

    # Inspect Network log
    api_endpoints = []
    if NETWORK_LOG_PATH.exists():
        with open(NETWORK_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    api_endpoints.append(data)
                except Exception:
                    pass

    print(f"\nFound {len(api_endpoints)} logged network call(s).")
    unique_endpoints = {}
    for entry in api_endpoints:
        parsed = urlparse(entry["url"])
        key = (entry["method"], parsed.path)
        if key not in unique_endpoints:
            unique_endpoints[key] = entry

    if unique_endpoints:
        print("\nDistinct Internal APIs detected:")
        for (m, p), sample in unique_endpoints.items():
            print(f"  - [{m}] {p}")

    # Inspect HTML fixtures
    analyzed_pages = []
    for f_path in html_files:
        content = f_path.read_text(encoding="utf-8", errors="ignore")
        title_match = re.search(r"<title>(.*?)</title>", content, re.IGNORECASE)
        title = title_match.group(1).strip() if title_match else "No Title"

        # Check framework
        framework = "Standard SSR / Static"
        if "__NEXT_DATA__" in content:
            framework = "Next.js"
        elif "__NUXT__" in content:
            framework = "Nuxt.js"

        # Check login state
        has_avatar = bool(re.search(r'class="[^"]*(avatar|user-menu|profile|account)[^"]*"', content, re.I))
        has_login_btn = bool(re.search(r'(đăng nhập|login|sign in)', content, re.I))

        # Check images
        img_tags = re.findall(r'<img\b[^>]*src=["\']([^"\']+)["\'][^>]*>', content, re.I)

        # Check FE / PE keywords
        has_fe = bool(re.search(r'\b(FE|Final Exam)\b', content))
        has_pe = bool(re.search(r'\b(PE|Practical Exam)\b', content))

        analyzed_pages.append({
            "file": f_path.name,
            "title": title,
            "framework": framework,
            "has_avatar": has_avatar,
            "has_login_btn": has_login_btn,
            "img_count": len(img_tags),
            "sample_imgs": img_tags[:3],
            "has_fe": has_fe,
            "has_pe": has_pe,
        })

    print("\nFixture Summary:")
    for p in analyzed_pages:
        print(f"  [{p['file']}]")
        print(f"    Title: {p['title']}")
        print(f"    Framework: {p['framework']} | Imgs: {p['img_count']} | FE: {p['has_fe']} | PE: {p['has_pe']}")

    print("\nAnalysis complete.")


if __name__ == "__main__":
    main()

