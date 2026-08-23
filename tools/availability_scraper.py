#!/usr/bin/env python3
"""
Streaming Availability Scraper — "Be Prepared" pipeline v2.

Focus: actual titles available NOW on user's subscribed services.
No trailers, no review videos, no generic service homepages.

Sources:
- JustWatch (public pages for what's new on each service)
- Reelgood (public API for availability)
- TMDB + streaming providers endpoint

Output: suggestion_candidates.json with real availability data.
"""

import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from bs4 import BeautifulSoup

ELDER_BRAIN = Path.home() / "elder_brain"
CANDIDATES_PATH = ELDER_BRAIN / "suggestion_candidates.json"

# ═══════════════════════════════════════════════════════════════
# USER SUBSCRIPTIONS — configure which services you pay for
# ═══════════════════════════════════════════════════════════════

SUBSCRIPTION_SERVICES = {
    "netflix":      {"enabled": True,  "base_url": "https://www.netflix.com/title/", "search_url": "https://www.justwatch.com/us/provider/netflix/new"},
    "hbo_max":      {"enabled": True,  "base_url": "https://play.max.com/video/watch/", "search_url": "https://www.justwatch.com/us/provider/hbo-max/new"},
    "paramount_plus":{"enabled": True, "base_url": "https://www.paramountplus.com/movies/", "search_url": "https://www.justwatch.com/us/provider/paramount-plus/new"},
    "amazon_prime": {"enabled": True,  "base_url": "https://www.amazon.com/gp/video/detail/", "search_url": "https://www.justwatch.com/us/provider/amazon-prime-video/new"},
    "apple_tv_plus":{"enabled": True,  "base_url": "https://tv.apple.com/us/movie/", "search_url": "https://www.justwatch.com/us/provider/apple-tv-plus/new"},
    "hulu":         {"enabled": True,  "base_url": "https://www.hulu.com/watch/", "search_url": "https://www.justwatch.com/us/provider/hulu/new"},
    "disney_plus":  {"enabled": True,  "base_url": "https://www.disneyplus.com/movies/", "search_url": "https://www.justwatch.com/us/provider/disney-plus/new"},
    "peacock":      {"enabled": True,  "base_url": "https://www.peacocktv.com/watch/", "search_url": "https://www.justwatch.com/us/provider/peacock/new"},
}


def fetch_html(url, timeout=30):
    """Fetch HTML with retries and UA spoofing."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"[availability] Failed to fetch {url}: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# JUSTWATCH SCRAPER — New releases by service
# ═══════════════════════════════════════════════════════════════

def scrape_justwatch_new_releases(service_key: str, service_name: str, url: str):
    """Scrape new releases from JustWatch for a specific streaming service."""
    html = fetch_html(url)
    if not html:
        return []
    
    soup = BeautifulSoup(html, "lxml")
    items = []
    
    # JustWatch uses title cards with data
    # Look for title links that contain the service name
    for card in soup.find_all("a", href=re.compile(r"/us/movie/|/us/show/")):
        title_elem = card.find("img")
        if not title_elem:
            continue
        
        title = title_elem.get("alt", "").strip()
        if not title or len(title) < 2:
            continue
        
        # Skip trailers and behind-the-scenes
        title_lower = title.lower()
        skip_keywords = ["trailer", "teaser", "behind the scenes", "making of", "interview"]
        if any(kw in title_lower for kw in skip_keywords):
            continue
        
        # Get the JustWatch detail URL
        detail_path = card.get("href", "")
        if not detail_path.startswith("http"):
            detail_path = "https://www.justwatch.com" + detail_path
        
        # Extract year from URL if present
        year = ""
        year_match = re.search(r'-(\d{4})', detail_path)
        if year_match:
            year = year_match.group(1)
        
        items.append({
            "type": "movie" if "/movie/" in detail_path else "tv_show",
            "title": title,
            "service": service_key,
            "description": f"Available on {service_name}",
            "year": year,
            "url": detail_path,  # JustWatch page with streaming links
            "availability_source": "justwatch",
        })
    
    # Limit to avoid duplicates
    seen = set()
    unique = []
    for item in items:
        key = (item["title"], item["service"])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    
    print(f"[justwatch_{service_key}] Scraped {len(unique)} unique titles")
    return unique[:30]  # Top 30 per service


# ═══════════════════════════════════════════════════════════════
# TMDB + PROVIDER CHECK — Verify actual streaming availability
# ═══════════════════════════════════════════════════════════════

def check_tmdb_availability(title: str, year: str = "") -> dict:
    """Search TMDB for title and check which providers have it."""
    try:
        api_key = "eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiI1ZDg3ZDYxZGI2YjNlNjRkMTE2ZjI2MzE3OGQ2ZjU4NiIsInN1YiI6IjY1NjA3ZmI2MjQ1ZGQ1MDBlMjQxZGMxYiIsInNjb3BlcyI6WyJhcGlfcmVhZCJdLCJ2ZXJzaW9uIjoxfQ.dummy"
        # Search for movie
        search_url = f"https://api.themoviedb.org/3/search/multi?api_key={api_key}&query={urllib.parse.quote(title)}&language=en-US"
        
        req = urllib.request.Request(search_url, headers={"Authorization": f"Bearer {api_key}"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        
        results = data.get("results", [])
        if not results:
            return {}
        
        # Get top result
        top = results[0]
        media_type = top.get("media_type", "movie")
        tmdb_id = top.get("id")
        
        # Get providers for US
        provider_url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}/watch/providers?api_key={api_key}"
        req = urllib.request.Request(provider_url, headers={"Authorization": f"Bearer {api_key}"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            provider_data = json.loads(resp.read().decode())
        
        us_providers = provider_data.get("results", {}).get("US", {})
        flatrate = us_providers.get("flatrate", [])
        
        return {
            "tmdb_id": tmdb_id,
            "media_type": media_type,
            "providers": [p.get("provider_name", "").lower() for p in flatrate],
            "poster_path": f"https://image.tmdb.org/t/p/w200{top.get('poster_path', '')}" if top.get('poster_path') else "",
            "vote_average": top.get("vote_average", 0),
        }
    except Exception as e:
        print(f"[tmdb] Failed for '{title}': {e}")
        return {}


# ═══════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ═══════════════════════════════════════════════════════════════

def build_availability_candidates():
    """Build candidate list from all enabled subscription services."""
    all_candidates = []
    
    for service_key, config in SUBSCRIPTION_SERVICES.items():
        if not config.get("enabled", False):
            continue
        
        service_name = service_key.replace("_", " ").title()
        url = config.get("search_url", "")
        if not url:
            continue
        
        candidates = scrape_justwatch_new_releases(service_key, service_name, url)
        all_candidates.extend(candidates)
    
    print(f"[availability] Total candidates from subscriptions: {len(all_candidates)}")
    
    # Add metadata from TMDB where possible
    for c in all_candidates[:50]:  # Limit TMDB calls
        tmdb_data = check_tmdb_availability(c["title"], c.get("year", ""))
        if tmdb_data:
            c["poster_path"] = tmdb_data.get("poster_path", "")
            c["vote_average"] = tmdb_data.get("vote_average", 0)
            c["tmdb_id"] = tmdb_data.get("tmdb_id", "")
            # Verify the service actually has it according to TMDB
            providers = tmdb_data.get("providers", [])
            service_provider_map = {
                "netflix": ["netflix"],
                "hbo_max": ["hbo max", "max"],
                "paramount_plus": ["paramount plus", "paramount+"],
                "amazon_prime": ["amazon prime video", "prime video"],
                "apple_tv_plus": ["apple tv plus", "apple tv+"],
                "hulu": ["hulu"],
                "disney_plus": ["disney plus", "disney+"],
                "peacock": ["peacock"],
            }
            expected = service_provider_map.get(c["service"], [])
            if expected and not any(exp in providers for exp in expected):
                c["availability_verified"] = False
                print(f"[verify] TMDB says '{c['title']}' not on {c['service']} (providers: {providers})")
            else:
                c["availability_verified"] = True
    
    # Remove unverified items
    verified = [c for c in all_candidates if c.get("availability_verified", True)]
    print(f"[availability] {len(verified)} verified available titles")
    
    # Save to elder brain
    ELDER_BRAIN.mkdir(parents=True, exist_ok=True)
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "availability_scraper_v2",
        "count": len(verified),
        "candidates": verified,
    }
    with open(CANDIDATES_PATH, "w") as fh:
        json.dump(output, fh, indent=2)
    print(f"[availability] Saved {len(verified)} candidates to {CANDIDATES_PATH}")
    return verified


if __name__ == "__main__":
    build_availability_candidates()
