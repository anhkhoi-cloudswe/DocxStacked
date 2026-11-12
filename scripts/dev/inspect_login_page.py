from pathlib import Path
from bs4 import BeautifulSoup

content = Path("data/fixtures/sample_media_lightbox_q1.html").read_text(encoding="utf-8")
soup = BeautifulSoup(content, "html.parser")

print("Login Form Inspection:")
form = soup.find("form")
if form:
    print("Form action:", form.get("action"))
    inputs = form.find_all("input")
    for inp in inputs:
        print(f"  Input: name={inp.get('name')} type={inp.get('type')}")

# Check connected accounts (Google, Facebook, etc.)
providers = soup.select(".button--provider, .button[data-provider], a[href*='connected_account']")
print(f"\nConnected account buttons ({len(providers)}):")
for p in providers:
    print("  Provider:", p.get_text(strip=True), "->", p.get("href"))

