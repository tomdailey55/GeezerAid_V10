#!/usr/bin/env python3
"""
IMDb Scraper — public pages, no API key, no signup.

Uses IMDb's public chart/list pages which contain structured data:
- Top Rated Movies (250)
- Most Popular Movies (trending)
- Top Rated TV Shows
- Popular TV Shows

All pages have title, year, rating, genre in the HTML.
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

IMDB_LISTS = {
    "top_movies": "https://www.imdb.com/chart/top/",
    "popular_movies": "https://www.imdb.com/chart/moviemeter/",
    "top_tv": "https://www.imdb.com/chart/toptv/",
    "popular_tv": "https://www.imdb.com/chart/tvmeter/",
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
        print(f"[imdb] Failed {url}: {e}")
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


# Simple title-to-genre inference from common keywords
TITLE_GENRE_HINTS = {
    "war": ["war", "drama"],
    "comedy": ["comedy"],
    "romance": ["romance", "drama"],
    "thriller": ["thriller"],
    "horror": ["horror"],
    "sci-fi": ["sci-fi"],
    "science fiction": ["sci-fi"],
    "fantasy": ["fantasy"],
    "documentary": ["documentary"],
    "musical": ["musical"],
    "animation": ["animation"],
    "western": ["western"],
    "crime": ["crime", "thriller"],
    "murder": ["crime", "mystery"],
    "detective": ["mystery", "crime"],
    "spy": ["thriller", "action"],
    "heist": ["thriller", "crime"],
    "love": ["romance", "drama"],
    "family": ["family", "drama"],
    "adventure": ["adventure"],
    "action": ["action"],
    "mystery": ["mystery"],
    "biography": ["biography", "drama"],
    "sports": ["sports", "drama"],
    "music": ["music", "drama"],
    "historical": ["historical", "drama"],
    "period": ["period drama", "drama"],
}


def _infer_genres(title):
    """Infer genres from title keywords."""
    title_lower = title.lower()
    genres = set()
    for keyword, glist in TITLE_GENRE_HINTS.items():
        if keyword in title_lower:
            genres.update(glist)
    return list(genres)


def parse_imdb_chart(html, list_type):
    """Parse IMDb chart HTML."""
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    items = []

    # IMDb charts use li tags with class containing "ipc-metadata-list__item"
    # Each item has title, year, rating
    rows = soup.find_all("li", class_=lambda c: c and "ipc-metadata-list-summary-item" in c)

    for row in rows:
        try:
            # Title — usually in an h3 or a specific anchor
            title_el = row.find("h3", class_=lambda c: c and "ipc-title__text" in c)
            if not title_el:
                title_el = row.find("a", class_=lambda c: c and "ipc-title-link-wrapper" in c)

            full_text = title_el.get_text(strip=True) if title_el else ""

            # IMDb format: "1. The Shawshank Redemption" or just "The Shawshank Redemption"
            # Remove ranking number
            title = re.sub(r'^\d+\.\s*', '', full_text).strip()

            # Year — usually in a span near the title
            year = ""
            year_span = row.find("span", class_=lambda c: c and "cli-title-metadata" in c)
            if year_span:
                year_text = year_span.get_text(strip=True)
                year_match = re.search(r'\b(\d{4})\b', year_text)
                if year_match:
                    year = year_match.group(1)

            # If year not found in metadata, try from title
            if not year:
                year_match = re.search(r'\((\d{4})\)', title)
                if year_match:
                    year = year_match.group(1)
                    title = title[:title.rfind("(")].strip()

            # Rating
            rating = 0.0
            rating_span = row.find("span", class_=lambda c: c and "ipc-rating-star" in c)
            if rating_span:
                rating_text = rating_span.get_text(strip=True)
                try:
                    rating = float(rating_text.split()[0])
                except (ValueError, IndexError):
                    pass

            # Infer genres from title
            genres = _infer_genres(title)

            # Build URL
            href = ""
            if title_el and title_el.name == "a":
                href = title_el.get("href", "")
            else:
                link = row.find("a", href=re.compile(r'/title/tt\d+'))
                if link:
                    href = link.get("href", "")

            imdb_id = ""
            id_match = re.search(r'/title/(tt\d+)', href)
            if id_match:
                imdb_id = id_match.group(1)

            if title and len(title) > 1:
                is_tv = "tv" in list_type
                items.append({
                    "type": "tv_show" if is_tv else "movie",
                    "service": "imdb_top" if "top" in list_type else "imdb_popular",
                    "title": title,
                    "description": "",
                    "year": year,
                    "release_date": "",
                    "genres": genres,
                    "vote_average": rating,
                    "poster_path": "",
                    "url": f"https://www.imdb.com/title/{imdb_id}/" if imdb_id else f"https://www.imdb.com/find?q={urllib.request.quote(title)}",
                    "imdb_id": imdb_id,
                })
        except Exception:
            continue

    return items


def fetch_imdb_list(list_key):
    """Fetch + cache an IMDb chart."""
    cached = _load_cache(f"imdb_{list_key}")
    if cached:
        return cached

    url = IMDB_LISTS.get(list_key)
    if not url:
        return []

    html = _fetch(url, delay=1.5)
    items = parse_imdb_chart(html, list_key)
    _save_cache(f"imdb_{list_key}", items)
    print(f"[imdb] {list_key}: {len(items)} items")
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


def fetch_all_imdb_candidates(taste):
    """Fetch all IMDb lists and score them."""
    all_items = []

    for list_key in IMDB_LISTS:
        items = fetch_imdb_list(list_key)
        for item in items:
            score, reason = score_item(item, taste)
            if score >= 0.15:
                item["match_score"] = score
                item["match_reason"] = reason
                all_items.append(item)

    all_items.sort(key=lambda x: x["match_score"], reverse=True)
    return all_items


if __name__ == "__main__":
    print("[imdb] Testing scraper...")
    top = fetch_imdb_list("top_movies")
    print(f"[imdb] Top 5 movies:")
    for c in top[:5]:
        print(f"  • {c['title'][:40]} ({c.get('year','?')}) rating={c.get('vote_average',0)} genres={c.get('genres',[])}")
