#!/usr/bin/env python3
"""
Availability Filter + URL Generator for GeezerAid recommendations.

Takes the raw output from streaming_scraper.py and:
1. Filters out non-playable content (trailers, reviews, YouTube list videos)
2. Generates real search URLs for subscription services
3. Filters by user's active subscriptions
4. Outputs clean suggestion_candidates.json

Usage:
    python availability_filter.py
"""

import json
import re
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

ELDER_BRAIN = Path.home() / "elder_brain"
RAW_CANDIDATES_PATH = ELDER_BRAIN / "suggestion_candidates_raw.json"
OUTPUT_PATH = ELDER_BRAIN / "suggestion_candidates.json"

# ═══════════════════════════════════════════════════════════════
# SUBSCRIPTION CONFIG — edit this to match your services
# ═══════════════════════════════════════════════════════════════

DEFAULT_SUBSCRIPTIONS = {
    "netflix": True,
    "hbo_max": True,
    "paramount_plus": True,
    "amazon_prime": True,
    "apple_tv_plus": True,
    "hulu": False,
    "disney_plus": False,
    "peacock": False,
}


def load_subscriptions():
    """Load user subscriptions from taste_profile.json or use defaults."""
    profile_path = ELDER_BRAIN / "taste_profile.json"
    if profile_path.exists():
        try:
            with open(profile_path) as fh:
                profile = json.load(fh)
            return profile.get("subscriptions", DEFAULT_SUBSCRIPTIONS)
        except Exception:
            pass
    return DEFAULT_SUBSCRIPTIONS


# ═══════════════════════════════════════════════════════════════
# SERVICE URL BUILDERS — generate real searchable links
# ═══════════════════════════════════════════════════════════════

SERVICE_URL_BUILDERS = {
    "netflix": lambda title: f"https://www.netflix.com/search?q={urllib.parse.quote(title)}",
    "hbo_max": lambda title: f"https://play.max.com/search?q={urllib.parse.quote(title)}",
    "paramount_plus": lambda title: f"https://www.paramountplus.com/search/?q={urllib.parse.quote(title)}",
    "amazon_prime": lambda title: f"https://www.amazon.com/s?k={urllib.parse.quote(title + ' prime video')}",
    "apple_tv_plus": lambda title: f"https://tv.apple.com/search?term={urllib.parse.quote(title)}",
    "hulu": lambda title: f"https://www.hulu.com/search?q={urllib.parse.quote(title)}",
    "disney_plus": lambda title: f"https://www.disneyplus.com/search?q={urllib.parse.quote(title)}",
    "peacock": lambda title: f"https://www.peacocktv.com/watch/search?q={urllib.parse.quote(title)}",
}


# ═══════════════════════════════════════════════════════════════
# CONTENT FILTERS
# ═══════════════════════════════════════════════════════════════

TRAILER_KEYWORDS = [
    "trailer", "teaser", "preview", "first look", "official clip",
    "behind the scenes", "making of", "interview", "review",
    "top 10", "10 best", "5 best", "7 best", "8 best", "best of",
    "you just can't miss", "nobody knows", "nobody is watching",
    "hidden gems", "underrated", "overlooked", "forgotten",
]


def is_playable_content(candidate: dict) -> bool:
    """Determine if a candidate is actual playable content vs a review/list."""
    title = candidate.get("title", "").lower()
    desc = (candidate.get("description", "") or "").lower()
    ctype = candidate.get("type", "").lower()
    service = candidate.get("service", "").lower()
    
    # FIRST: Reject by type — YouTube reviews and list videos are never playable content
    if ctype in ("youtube_review", "film_review"):
        return False
    
    # SECOND: Reject by title keywords (catches list videos even with streaming service detected)
    reject_keywords = [
        "trailer", "teaser", "preview", "first look", "official clip",
        "behind the scenes", "making of", "interview", "review",
        "top 10", "10 best", "5 best", "7 best", "8 best", "best of",
        "top 5", "top 7", "top 8", "top new",
        "you just can't miss", "nobody knows", "nobody is watching",
        "no one is watching", "hidden gems", "underrated", "overlooked",
        "forgotten", "amazing", "to watch right now", "released from",
        "#shorts", "shortsvideo", "shorts video",
        "curated list", "watch right now", "new releases",
    ]
    for kw in reject_keywords:
        if kw in title or kw in desc:
            return False
    
    # THIRD: Duration check for YouTube videos under 15 minutes
    duration = candidate.get("duration", "")
    if duration:
        parts = duration.split(":")
        if len(parts) == 2:  # MM:SS
            try:
                mins = int(parts[0])
                if mins < 15:
                    return False
            except ValueError:
                pass
        elif len(parts) == 3:  # HH:MM:SS
            try:
                hours = int(parts[0])
                if hours < 1:
                    return False
            except ValueError:
                pass
    
    # FOURTH: Allow if it's from a real streaming service
    if service in ("netflix", "hbo_max", "paramount_plus", "amazon_prime", 
                    "apple_tv_plus", "hulu", "disney_plus", "peacock"):
        return True
    
    # Reject multi-service YouTube lists
    if service == "multi_service":
        return False
    
    return False


def parse_release_date(date_str: str) -> datetime:
    """Parse various date formats into a datetime. Returns 1970-01-01 if unparseable."""
    if not date_str:
        return datetime(1970, 1, 1)
    
    # Common formats: "Aug. 19", "Aug 19", "August 19", "Aug. 19, HBO", "2026-08-19"
    cleaned = re.sub(r'\s*(?:HBO|Netflix|Max|Paramount\+).*', '', date_str, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r'[^\w\s]', '', cleaned)  # Remove punctuation except spaces
    cleaned = cleaned.strip()
    
    # Try various formats
    current_year = datetime.now().year
    formats = [
        "%B %d %Y",
        "%B %d",
        "%b %d %Y", 
        "%b %d",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(f"{cleaned} {current_year}", "%s %d %Y" if "%d" in fmt else "%s %Y")
            return dt
        except ValueError:
            pass
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            pass
    
    # Try ISO format
    try:
        return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
    except ValueError:
        pass
    
    return datetime(1970, 1, 1)


def is_subscribed_service(candidate: dict, subscriptions: dict) -> bool:
    """Check if the candidate's service is in user's active subscriptions."""
    service = candidate.get("service", "").lower()
    
    # Map service aliases
    service_map = {
        "netflix": "netflix",
        "hbo_max": "hbo_max",
        "hbo": "hbo_max",
        "max": "hbo_max",
        "paramount_plus": "paramount_plus",
        "paramount": "paramount_plus",
        "paramount+": "paramount_plus",
        "amazon_prime": "amazon_prime",
        "prime": "amazon_prime",
        "apple_tv_plus": "apple_tv_plus",
        "apple tv+": "apple_tv_plus",
        "hulu": "hulu",
        "disney_plus": "disney_plus",
        "disney+": "disney_plus",
        "peacock": "peacock",
    }
    
    mapped = service_map.get(service, service)
    return subscriptions.get(mapped, False)


def generate_proper_url(candidate: dict) -> str:
    """Generate a real searchable URL for the content."""
    service = candidate.get("service", "").lower()
    title = candidate.get("title", "")
    existing_url = candidate.get("url", "")
    
    # If it already has a specific URL (not a homepage), keep it
    if existing_url and existing_url not in (
        "https://www.netflix.com",
        "https://www.hbomax.com",
        "https://www.paramountplus.com",
        "",
    ):
        return existing_url
    
    # Generate search URL for the service
    builder = SERVICE_URL_BUILDERS.get(service)
    if builder and title:
        return builder(title)
    
    return existing_url


def filter_and_enhance_candidates(raw_candidates: list, subscriptions: dict) -> list:
    """Filter raw candidates and generate proper URLs."""
    filtered = []
    seen_titles = set()
    
    for c in raw_candidates:
        # Must be playable content (not trailer/review)
        if not is_playable_content(c):
            continue
        
        # Must be on a subscribed service
        if not is_subscribed_service(c, subscriptions):
            continue
        
        # Deduplicate by title+service
        key = (c.get("title", "").lower(), c.get("service", ""))
        if key in seen_titles:
            continue
        seen_titles.add(key)
        
        # Generate proper URL
        c["url"] = generate_proper_url(c)
        c["available"] = True
        c["subscription_required"] = True
        
        # Determine availability window
        release_date = parse_release_date(c.get("release_date", ""))
        now = datetime.now()
        days_until = (release_date - now).days
        
        if days_until <= 0 or release_date.year == 1970:
            c["availability"] = "available_now"
        elif days_until <= 14:
            c["availability"] = "coming_soon"
            c["days_until"] = days_until
        else:
            c["availability"] = "future"
        
        filtered.append(c)
    
    return filtered


def main():
    """Run the availability filter pipeline."""
    subscriptions = load_subscriptions()
    print(f"[filter] Active subscriptions: {[k for k,v in subscriptions.items() if v]}")
    
    # Load raw candidates (from streaming_scraper.py)
    raw = {"candidates": []}
    if RAW_CANDIDATES_PATH.exists():
        try:
            with open(RAW_CANDIDATES_PATH) as fh:
                raw = json.load(fh)
        except Exception as e:
            print(f"[filter] Failed to load raw candidates: {e}")
    
    raw_candidates = raw.get("candidates", [])
    print(f"[filter] Loaded {len(raw_candidates)} raw candidates")
    
    # Filter and enhance
    filtered = filter_and_enhance_candidates(raw_candidates, subscriptions)
    print(f"[filter] {len(filtered)} candidates after filtering")
    
    # Save output
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "availability_filter_v2",
        "subscriptions": {k:v for k,v in subscriptions.items() if v},
        "count": len(filtered),
        "candidates": filtered,
    }
    
    ELDER_BRAIN.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as fh:
        json.dump(output, fh, indent=2)
    
    print(f"[filter] Saved {len(filtered)} verified candidates to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
