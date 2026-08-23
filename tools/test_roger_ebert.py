#!/usr/bin/env python3
import urllib.request, re
from bs4 import BeautifulSoup

def fetch_html(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", errors="replace")

url = "https://www.rogerebert.com/reviews"
html = fetch_html(url)
soup = BeautifulSoup(html, "lxml")

# Try different selectors
print("=== h2 tags ===")
for el in soup.find_all("h2", limit=10):
    text = el.get_text(strip=True)
    if text and 5 < len(text) < 80:
        print(f"  {text}")

print("\n=== h3 tags ===")
for el in soup.find_all("h3", limit=10):
    text = el.get_text(strip=True)
    if text and 5 < len(text) < 80:
        print(f"  {text}")

print("\n=== articles with class ===")
for el in soup.find_all("article", limit=10):
    h = el.find(["h2","h3","h4"])
    if h:
        print(f"  {h.get_text(strip=True)[:80]}")

print("\n=== a tags with review in href ===")
for el in soup.find_all("a", href=re.compile(r"/reviews/"), limit=10):
    text = el.get_text(strip=True)
    if text and 5 < len(text) < 80 and text.lower() not in ("reviews", "read review"):
        print(f"  {text} | href={el.get('href','')}")
