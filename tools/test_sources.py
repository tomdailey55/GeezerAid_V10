#!/usr/bin/env python3
"""Quick test to see which new sources return data."""
import urllib.request
from bs4 import BeautifulSoup
import re

def fetch_html(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return f"ERROR: {e}"

# Test sources
sources = [
    ("Rotten Tomatoes - Certified Fresh", "https://www.rottentomatoes.com/browse/movies_in_theaters/sort:popular"),
    ("BBC Culture", "https://www.bbc.com/culture/film"),
    ("Vulture Streaming", "https://www.vulture.com/streaming/"),
    ("NPR Arts", "https://www.npr.org/sections/movies/"),
    ("Criterion Channel", "https://www.criterionchannel.com/whats-new"),
    ("Criterion - Current", "https://www.criterion.com/current/"),
    ("Letterboxd - Popular", "https://letterboxd.com/films/popular/"),
    ("Film Comment", "https://www.filmlinc.org/film-comment/"),
]

for name, url in sources:
    print(f"\n{'='*60}")
    print(f"TESTING: {name}")
    print(f"URL: {url}")
    html = fetch_html(url)
    if html.startswith("ERROR:"):
        print(f"RESULT: {html}")
        continue
    
    soup = BeautifulSoup(html, "lxml")
    titles = []
    
    # Try common selectors
    for sel in ["h2", "h3", "h4", ".film-title", ".movie-title", ".title", "a[href*='/film/']"]:
        for el in soup.select(sel)[:5]:
            text = el.get_text(strip=True)
            if text and len(text) > 2 and len(text) < 100:
                titles.append(text)
        if titles:
            break
    
    if titles:
        print(f"RESULT: OK — found {len(titles)} sample titles:")
        for t in titles[:3]:
            print(f"  - {t[:80]}")
    else:
        # Check if page has any recognizable content
        body_text = soup.get_text(separator=" ", strip=True)[:200]
        print(f"RESULT: No titles found. Page text preview: {body_text[:100]}...")

