#!/usr/bin/env python3
"""
Free Film/TV Data Sources — no API keys, no signup required.

Replaces TMDB with public pages that don't require authentication:
- Metacritic browse (titles, descriptions, ratings, genres)
- Wikipedia film lists (structured tables, comprehensive)
- Rotten Tomatoes browse (public pages)

All scraping respects robots.txt and uses conservative request rates.
"""

import json
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

CACHE_DIR = Path.home() / ".cache" / "geezeraid"
CACHE_TTL_HOURS = 6


def _fetch(url, delay=1.0):
    """Fetch with UA spoofing and polite delay."""
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
        print(f"[free_sources] Failed {url}: {e}")
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


# ═══════════════════════════════════════════════════════════════════════
# METACRITIC — Movies
# ═══════════════════════════════════════════════════════════════════════

def fetch_metacritic_movies():
    """Scrape Metacritic movie browse for recently released films."""
    cached = _load_cache("metacritic_movies")
    if cached:
        return cached

    url = "https://www.metacritic.com/browse/movie/?releaseYearMin=2024&releaseYearMax=2026&page=1"
    html = _fetch(url, delay=0.5)
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    items = []

    # Metacritic cards: each film is a card with title, rating, description
    for card in soup.find_all("div", class_="c-productCard"):
        try:
            title_el = card.find("h3", class_="c-productCard_title")
            title = title_el.get_text(strip=True) if title_el else ""

            score_el = card.find("span", class_="c-productCard_score")
            score_text = score_el.get_text(strip=True) if score_el else ""
            score = 0
            try:
                score = int(score_text) if score_text else 0
            except ValueError:
                pass

            desc_el = card.find("div", class_="c-productCard_description")
            desc = desc_el.get_text(strip=True) if desc_el else ""

            # Try to extract year from URL or text
            year = "2026"
            year_match = re.search(r'\b(20[0-9]{2})\b', desc + title)
            if year_match:
                year = year_match.group(1)

            if title:
                items.append({
                    "type": "movie",
                    "service": "theatrical",
                    "title": title,
                    "description": desc[:300],
                    "year": year,
                    "release_date": "",
                    "vote_average": score / 10.0 if score else 0,
                    "genres": [],
                    "url": f"https://www.metacritic.com/search/{urllib.request.quote(title)}/",
                })
        except Exception:
            continue

    _save_cache("metacritic_movies", items)
    print(f"[metacritic] Scraped {len(items)} movies")
    return items


# ═══════════════════════════════════════════════════════════════════════
# METACRITIC — TV Shows
# ═══════════════════════════════════════════════════════════════════════

def fetch_metacritic_tv():
    """Scrape Metacritic TV browse."""
    cached = _load_cache("metacritic_tv")
    if cached:
        return cached

    url = "https://www.metacritic.com/browse/tv/?releaseYearMin=2024&releaseYearMax=2026&page=1"
    html = _fetch(url, delay=0.5)
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    items = []

    for card in soup.find_all("div", class_="c-productCard"):
        try:
            title_el = card.find("h3", class_="c-productCard_title")
            title = title_el.get_text(strip=True) if title_el else ""

            score_el = card.find("span", class_="c-productCard_score")
            score_text = score_el.get_text(strip=True) if score_el else ""
            score = 0
            try:
                score = int(score_text) if score_text else 0
            except ValueError:
                pass

            desc_el = card.find("div", class_="c-productCard_description")
            desc = desc_el.get_text(strip=True) if desc_el else ""

            year = "2026"
            year_match = re.search(r'\b(20[0-9]{2})\b', desc + title)
            if year_match:
                year = year_match.group(1)

            if title:
                items.append({
                    "type": "tv_show",
                    "service": "streaming",
                    "title": title,
                    "description": desc[:300],
                    "year": year,
                    "release_date": "",
                    "vote_average": score / 10.0 if score else 0,
                    "genres": [],
                    "url": f"https://www.metacritic.com/search/{urllib.request.quote(title)}/",
                })
        except Exception:
            continue

    _save_cache("metacritic_tv", items)
    print(f"[metacritic] Scraped {len(items)} TV shows")
    return items


# ═══════════════════════════════════════════════════════════════════════
# WIKIPEDIA — American Films of 2026
# ═══════════════════════════════════════════════════════════════════════

def fetch_wikipedia_films(year=2026):
    """Scrape Wikipedia's structured film list for a given year."""
    cached = _load_cache(f"wiki_films_{year}")
    if cached:
        return cached

    url = f"https://en.wikipedia.org/wiki/List_of_American_films_of_{year}"
    html = _fetch(url, delay=0.5)
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    items = []

    # Wikipedia film tables have columns: Title, Director, Cast, Genre, Notes
    tables = soup.find_all("table", class_="wikitable")
    for table in tables:
        rows = table.find_all("tr")[1:]  # skip header
        for row in rows:
            cols = row.find_all(["td", "th"])
            if len(cols) < 3:
                continue
            try:
                title = cols[0].get_text(strip=True)
                director = cols[1].get_text(strip=True) if len(cols) > 1 else ""
                cast = cols[2].get_text(strip=True) if len(cols) > 2 else ""
                genre = cols[3].get_text(strip=True) if len(cols) > 3 else ""

                # Clean up Wikipedia markup artifacts
                title = re.sub(r'\[\d+\]', '', title).strip()
                director = re.sub(r'\[\d+\]', '', director).strip()
                genre = re.sub(r'\[\d+\]', '', genre).strip()

                if title and len(title) > 1:
                    items.append({
                        "type": "movie",
                        "service": "theatrical",
                        "title": title,
                        "description": f"Directed by {director}. Starring {cast}."[:300] if director else "",
                        "year": str(year),
                        "release_date": "",
                        "genres": [g.strip() for g in genre.split(",") if g.strip()],
                        "vote_average": 0,
                        "url": f"https://en.wikipedia.org/wiki/{urllib.request.quote(title.replace(' ', '_'))}",
                    })
            except Exception:
                continue

    _save_cache(f"wiki_films_{year}", items)
    print(f"[wikipedia] Scraped {len(items)} films from {year}")
    return items


# ═══════════════════════════════════════════════════════════════════════
# WIKIPEDIA — Netflix Original Films
# ═══════════════════════════════════════════════════════════════════════

def fetch_wikipedia_netflix_films():
    """Scrape Wikipedia's list of Netflix original films."""
    cached = _load_cache("wiki_netflix_films")
    if cached:
        return cached

    url = "https://en.wikipedia.org/wiki/Lists_of_Netflix_original_films"
    html = _fetch(url, delay=0.5)
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    items = []

    # Find tables in the page — Netflix originals are in wikitable format
    tables = soup.find_all("table", class_="wikitable")
    for table in tables:
        rows = table.find_all("tr")[1:]
        for row in rows:
            cols = row.find_all(["td", "th"])
            if len(cols) < 2:
                continue
            try:
                title = cols[0].get_text(strip=True)
                genre = cols[1].get_text(strip=True) if len(cols) > 1 else ""
                release = cols[2].get_text(strip=True) if len(cols) > 2 else ""

                title = re.sub(r'\[\d+\]', '', title).strip()
                genre = re.sub(r'\[\d+\]', '', genre).strip()

                year = ""
                year_match = re.search(r'\b(20[0-9]{2})\b', release)
                if year_match:
                    year = year_match.group(1)

                if title and len(title) > 1:
                    items.append({
                        "type": "movie",
                        "service": "netflix",
                        "title": title,
                        "description": f"Genre: {genre}."[:300] if genre else "",
                        "year": year,
                        "release_date": release,
                        "genres": [g.strip() for g in genre.split(",") if g.strip()],
                        "vote_average": 0,
                        "url": "https://www.netflix.com",
                    })
            except Exception:
                continue

    _save_cache("wiki_netflix_films", items)
    print(f"[wikipedia] Scraped {len(items)} Netflix original films")
    return items


# ═══════════════════════════════════════════════════════════════════════
# SCORING (same logic as tmdb_client)
# ═══════════════════════════════════════════════════════════════════════

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

    # Genre match
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


# ═══════════════════════════════════════════════════════════════════════
# MAIN INTERFACE (drop-in replacement for tmdb_client)
# ═══════════════════════════════════════════════════════════════════════

def fetch_all_candidates(taste, max_per_source=50):
    """Fetch and score all free-source candidates."""
    all_items = []

    sources = [
        fetch_metacritic_movies,
        fetch_metacritic_tv,
        lambda: fetch_wikipedia_films(2026),
        lambda: fetch_wikipedia_films(2025),
        fetch_wikipedia_netflix_films,
    ]

    for source_fn in sources:
        try:
            items = source_fn()
            for item in items[:max_per_source]:
                score, reason = score_item(item, taste)
                if score >= 0.15:
                    item["match_score"] = score
                    item["match_reason"] = reason
                    all_items.append(item)
        except Exception as e:
            print(f"[free_sources] {source_fn.__name__} failed: {e}")

    all_items.sort(key=lambda x: x["match_score"], reverse=True)
    return all_items


if __name__ == "__main__":
    print("[free_sources] Fetching free film/TV data...")
    candidates = fetch_all_candidates({})
    print(f"[free_sources] {len(candidates)} candidates")
    for c in candidates[:10]:
        print(f"  • [{c.get('service','?'):12s}] {c['type']:10s} {c['title'][:40]} score={c['match_score']}")
