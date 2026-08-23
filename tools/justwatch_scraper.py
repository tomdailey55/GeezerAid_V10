#!/usr/bin/env python3
"""
JustWatch Scraper — public pages, no API key, no signup.

JustWatch shows what's new/popular on each streaming service with:
- Title, year, poster
- Genre tags, rating, runtime
- Direct deeplinks to Netflix, Prime, HBO, etc.

Uses country-specific public pages. Conservative delays.
"""

import json
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

CACHE_DIR = Path.home() / ".cache" / "geezeraid"
CACHE_TTL_HOURS = 4


JUSTWATCH_PAGES = {
    "netflix": "https://www.justwatch.com/us/provider/netflix/new",
    "prime_video": "https://www.justwatch.com/us/provider/amazon-prime-video/new",
    "hbo_max": "https://www.justwatch.com/us/provider/hbo-max/new",
    "paramount_plus": "https://www.justwatch.com/us/provider/paramount-plus/new",
    "apple_tv": "https://www.justwatch.com/us/provider/apple-tv-plus/new",
    "hulu": "https://www.justwatch.com/us/provider/hulu/new",
}


def _fetch(url, delay=1.0):
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        time.sleep(delay)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"[justwatch] Failed {url}: {e}")
        return None


def _cache_path(name):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"{name}.json"


def _load_cache(name):
    cp = _cache_path(name)
    if cp.exists():
        mtime = datetime.fromtimestamp(cp.stat().st_mtime, tz=timezone.utc)
        if (datetime.now(timezone.utc) - mtime).seconds < CACHE_TTL_HOURS * 3600:
            with open(cp) as fh:
                return json.load(fh)
    return None


def _save_cache(name, data):
    with open(_cache_path(name), "w") as fh:
        json.dump(data, fh)


def parse_justwatch(html, service_name):
    """Parse JustWatch new releases page."""
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    items = []

    # JustWatch tiles have class starting with "title-list-grid__item"
    # Each tile contains: poster, title, year, genre, rating
    tiles = soup.find_all("div", class_=lambda c: c and "title-list-grid__item" in c)

    for tile in tiles:
        try:
            # Title
            title_el = tile.find("a", class_=lambda c: c and "title-list-grid__item--link" in c)
            if not title_el:
                title_el = tile.find("a")
            title = title_el.get_text(strip=True) if title_el else ""
            href = title_el.get("href", "") if title_el else ""

            # Extract year from title (usually "Title (2025)")
            year = ""
            year_match = re.search(r'\((\d{4})\)$', title)
            if year_match:
                year = year_match.group(1)
                title = title[:year_match.start()].strip()

            # Poster
            img = tile.find("img")
            poster = img.get("src", "") if img else ""

            # Rating — look for text like "7.2" near rating classes
            rating = 0.0
            rating_el = tile.find("span", class_=lambda c: c and "rating" in c.lower())
            if rating_el:
                try:
                    rating = float(rating_el.get_text(strip=True))
                except ValueError:
                    pass

            # Genre text
            genre_text = ""
            genre_el = tile.find("span", class_=lambda c: c and "genre" in c.lower())
            if genre_el:
                genre_text = genre_el.get_text(strip=True)

            genres = [g.strip() for g in genre_text.split(",") if g.strip()]

            if title:
                items.append({
                    "type": "tv_movie",
                    "service": service_name,
                    "title": title,
                    "description": "",
                    "year": year,
                    "release_date": "",
                    "genres": genres,
                    "vote_average": rating,
                    "poster_path": poster,
                    "url": f"https://www.justwatch.com{href}" if href.startswith("/") else href,
                })
        except Exception:
            continue

    return items


def fetch_service(service_key):
    """Fetch + cache a single JustWatch service page."""
    cached = _load_cache(f"jw_{service_key}")
    if cached:
        return cached

    url = JUSTWATCH_PAGES.get(service_key)
    if not url:
        return []

    html = _fetch(url, delay=0.8)
    items = parse_justwatch(html, service_key)
    _save_cache(f"jw_{service_key}", items)
    print(f"[justwatch] {service_key}: {len(items)} items")
    return items


def score_item(item, taste):
    """Score against taste profile."""
    film = taste.get("film", {})
    tv = taste.get("tv", {})
    fav_directors = [d.lower() for d in film.get("directors", [])]
    fav_genres = [g.lower() for g in film.get("genres", []) + tv.get("genres", [])]
    avoid = [a.lower() for a in film.get("avoid", []) + tv.get("avoid", [])]
    fav_shows = [s.lower() for s in tv.get("shows", [])]

    title = item.get("title", "").lower()
    desc = item.get("description", "").lower()
    genres = [g.lower() for g in item.get("genres", [])]

    combined_text = f"{title} {desc}"
    if any(a in combined_text for a in avoid):
        return 0.0, "avoided"

    score = 0.0
    reasons = []

    # Genre match (JustWatch has good genre tags)
    genre_matches = [g for g in genres if any(fav in g for fav in fav_genres)]
    if genre_matches:
        score += min(0.4 + len(genre_matches) * 0.1, 0.7)
        reasons.append("matching_genre")

    # Director match
    if any(d in title or d in desc for d in fav_directors):
        score += 0.6
        reasons.append("favorite_director")

    # Show match
    if any(s in title or s in desc for s in fav_shows):
        score += 0.5
        reasons.append("related_show")

    # Era
    eras = film.get("eras", [])
    year = item.get("year", "")
    if year and any(year.startswith(e[:2]) for e in eras):
        score += 0.1
        reasons.append("era_hint")

    # Rating bonus
    vote = item.get("vote_average", 0)
    if vote >= 7.5:
        score += 0.05
        reasons.append("highly_rated")
    elif vote >= 6.0:
        score += 0.02
        reasons.append("decent_rated")

    return round(min(score, 1.0), 2), ",".join(reasons) if reasons else "no_match"


def fetch_all_justwatch_candidates(taste):
    """Fetch all enabled JustWatch services and score them."""
    all_items = []
    sources = taste.get("sources", {})

    service_map = {
        "netflix_enabled": "netflix",
        "hbo_enabled": "hbo_max",
        "paramount_enabled": "paramount_plus",
        # Add more as needed
    }

    for flag, service_key in service_map.items():
        if sources.get(flag, False):
            items = fetch_service(service_key)
            for item in items:
                score, reason = score_item(item, taste)
                if score >= 0.15:
                    item["match_score"] = score
                    item["match_reason"] = reason
                    all_items.append(item)

    all_items.sort(key=lambda x: x["match_score"], reverse=True)
    return all_items


if __name__ == "__main__":
    print("[justwatch] Testing scraper...")
    # Test Netflix
    netflix = fetch_service("netflix")
    print(f"[justwatch] Netflix top 5:")
    for c in netflix[:5]:
        print(f"  • {c['title'][:45]} ({c.get('year','?')}) genres={c.get('genres',[])} rating={c.get('vote_average',0)}")
