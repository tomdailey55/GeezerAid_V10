#!/usr/bin/env python3
import urllib.request, re
from bs4 import BeautifulSoup

def fetch_html(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return f"ERROR: {e}"

sources = [
    ("Vulture Best Movies", "https://www.vulture.com/article/best-movies-on-netflix-right-now.html"),
    ("NPR Movies", "https://www.npr.org/sections/movies/"),
    ("Criterion Current", "https://www.criterion.com/current/"),
    ("Roger Ebert", "https://www.rogerebert.com/reviews"),
    ("Guardian Film", "https://www.theguardian.com/uk/film"),
    ("Paste Movies", "https://www.pastemagazine.com/movies/"),
    ("Slant Film", "https://www.slantmagazine.com/film/"),
]

for name, url in sources:
    print(f"\n{'='*60}")
    print(f"TESTING: {name}")
    html = fetch_html(url)
    if html.startswith("ERROR:"):
        print(f"RESULT: {html}")
        continue
    
    soup = BeautifulSoup(html, "lxml")
    titles = []
    for tag in ["h2", "h3", "h4", "h1"]:
        for el in soup.find_all(tag, limit=10):
            text = el.get_text(strip=True)
            if text and 5 < len(text) < 80 and not text.lower().startswith(("home", "about", "contact", "subscribe", "search", "sign in", "login")):
                titles.append(text)
    for cls in ["film-title", "movie-title", "title", "headline", "entry-title"]:
        for el in soup.find_all(class_=re.compile(cls, re.I), limit=5):
            text = el.get_text(strip=True)
            if text and 5 < len(text) < 80:
                titles.append(text)
    
    if titles:
        print(f"RESULT: OK — sample titles:")
        for t in titles[:5]:
            print(f"  - {t[:80]}")
    else:
        body_text = soup.get_text(separator=" ", strip=True)[:200]
        print(f"RESULT: No titles. Preview: {body_text[:100]}...")

