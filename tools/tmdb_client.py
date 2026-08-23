#!/usr/bin/env python3
"""
TMDB Client — enriched film/TV data for the streaming suggestion pipeline.

Requires a free TMDB API key (v3 auth). Get one at:
  https://www.themoviedb.org/settings/api

Set TMDB_API_KEY env var, create ~/.tmdb_api_key, or pass directly.

Provides:
- Trending movies + TV (day/week)
- New theatrical releases
- Popular streaming content (with TMDB's watch-provider filters)
- Genre, director, cast, rating, overview enrichment
- Caching to reduce API calls
"""

import json
import os
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

API_BASE = "https://api.themoviedb.org/3"
CACHE_DIR = Path.home() / ".cache" / "geezeraid"
CACHE_TTL = timedelta(hours=6)


def _get_api_key():
    """Resolve TMDB API key from env, file, or return None."""
    key = os.environ.get("TMDB_API_KEY", "")
    if key:
        return key
    key_file = Path.home() / ".tmdb_api_key"
    if key_file.exists():
        return key_file.read_text().strip()
    return None


def _cached_get(endpoint: str, params: dict) -> dict:
    """Fetch from TMDB with simple file caching."""
    key = _get_api_key()
    if not key:
        raise RuntimeError(
            "TMDB API key required. Get a free key at https://www.themoviedb.org/settings/api "
            "and set TMDB_API_KEY env var or save to ~/.tmdb_api_key"
        )

    query = "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in params.items())
    url = f"{API_BASE}{endpoint}?api_key={key}&{query}"
    cache_key = f"{endpoint.replace('/', '_')}_{hash(query)}.json"
    cache_path = CACHE_DIR / cache_key

    # Check cache
    if cache_path.exists():
        mtime = datetime.fromtimestamp(cache_path.stat().st_mtime, tz=timezone.utc)
        if datetime.now(timezone.utc) - mtime < CACHE_TTL:
            with open(cache_path) as fh:
                return json.load(fh)

    # Fetch fresh
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"[tmdb] API error: {e.code} {e.reason}")
        return {}

    # Save cache
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w") as fh:
        json.dump(data, fh)
    return data


def fetch_trending_movies(time_window="week", page=1):
    """Trending movies. time_window: 'day' or 'week'."""
    data = _cached_get("/trending/movie/week", {"page": page})
    results = data.get("results", [])
    items = []
    for r in results:
        items.append(_normalize_movie(r))
    return items


def fetch_trending_tv(time_window="week", page=1):
    """Trending TV shows."""
    data = _cached_get("/trending/tv/week", {"page": page})
    results = data.get("results", [])
    items = []
    for r in results:
        items.append(_normalize_tv(r))
    return items


def fetch_now_playing(page=1, region="US"):
    """Currently in theaters."""
    data = _cached_get("/movie/now_playing", {"page": page, "region": region})
    results = data.get("results", [])
    items = []
    for r in results:
        items.append(_normalize_movie(r))
    return items


def fetch_popular_streaming(provider_id=None, page=1, region="US"):
    """
    Popular movies with watch provider filter.
    Common provider IDs: Netflix=8, HBO Max=384, Paramount+=531, Apple TV=350
    """
    params = {"page": page, "region": region, "sort_by": "popularity.desc"}
    if provider_id:
        params["with_watch_providers"] = provider_id
        params["watch_region"] = region
    data = _cached_get("/discover/movie", params)
    results = data.get("results", [])
    items = []
    for r in results:
        items.append(_normalize_movie(r))
    return items


def _normalize_movie(r):
    """Flatten TMDB movie record into our candidate format."""
    genres = [g["name"] for g in r.get("genre_ids", [])]
    return {
        "type": "movie",
        "service": "theatrical",  # will be refined by provider lookup later
        "title": r.get("title", ""),
        "description": r.get("overview", ""),
        "release_date": r.get("release_date", ""),
        "year": r.get("release_date", "")[:4] if r.get("release_date") else "",
        "genres": genres,
        "popularity": r.get("popularity", 0),
        "vote_average": r.get("vote_average", 0),
        "poster_path": f"https://image.tmdb.org/t/p/w200{r['poster_path']}" if r.get("poster_path") else "",
        "url": f"https://www.themoviedb.org/movie/{r.get('id')}",
        "tmdb_id": r.get("id"),
    }


def _normalize_tv(r):
    """Flatten TMDB TV record into our candidate format."""
    genres = [g["name"] for g in r.get("genre_ids", [])]
    return {
        "type": "tv_show",
        "service": "streaming",
        "title": r.get("name", ""),
        "description": r.get("overview", ""),
        "release_date": r.get("first_air_date", ""),
        "year": r.get("first_air_date", "")[:4] if r.get("first_air_date") else "",
        "genres": genres,
        "popularity": r.get("popularity", 0),
        "vote_average": r.get("vote_average", 0),
        "poster_path": f"https://image.tmdb.org/t/p/w200{r['poster_path']}" if r.get("poster_path") else "",
        "url": f"https://www.themoviedb.org/tv/{r.get('id')}",
        "tmdb_id": r.get("id"),
    }


def score_tmdb_item(item, taste):
    """
    Score a TMDB-normalized item against taste profile.
    Returns (score, reason_string).
    """
    film = taste.get("film", {})
    tv = taste.get("tv", {})
    fav_directors = [d.lower() for d in film.get("directors", [])]
    fav_genres = [g.lower() for g in film.get("genres", []) + tv.get("genres", [])]
    avoid = [a.lower() for a in film.get("avoid", []) + tv.get("avoid", [])]
    fav_shows = [s.lower() for s in tv.get("shows", [])]

    title = item.get("title", "").lower()
    desc = item.get("description", "").lower()
    genres = [g.lower() for g in item.get("genres", [])]

    # Rejections
    combined_text = f"{title} {desc}"
    if any(a in combined_text for a in avoid):
        return 0.0, "avoided"

    score = 0.0
    reasons = []

    # Genre match (strongest signal for TMDB — we have actual genre IDs)
    genre_matches = [g for g in genres if any(fav in g for fav in fav_genres)]
    if genre_matches:
        score += min(0.4 + len(genre_matches) * 0.1, 0.7)
        reasons.append("matching_genre")

    # Director match (TMDB doesn't always include director in basic results,
    # but we check description for mentions)
    if any(d in title or d in desc for d in fav_directors):
        score += 0.6
        reasons.append("favorite_director")

    # Show/franchise match (for TV)
    if any(s in title or s in desc for s in fav_shows):
        score += 0.5
        reasons.append("related_show")

    # Era hint
    eras = film.get("eras", [])
    year = item.get("year", "")
    if year and any(year.startswith(e[:2]) for e in eras):
        score += 0.1
        reasons.append("era_hint")

    # Rating bonus (higher-rated content gets a small bump)
    vote = item.get("vote_average", 0)
    if vote >= 7.5:
        score += 0.05
        reasons.append("highly_rated")
    elif vote >= 6.0:
        score += 0.02
        reasons.append("decent_rated")

    return round(min(score, 1.0), 2), ",".join(reasons) if reasons else "no_match"


def fetch_all_tmdb_candidates(taste, max_pages=2):
    """Fetch and score TMDB candidates."""
    all_items = []

    # Trending movies
    for page in range(1, max_pages + 1):
        movies = fetch_trending_movies(page=page)
        for item in movies:
            score, reason = score_tmdb_item(item, taste)
            if score >= 0.15:
                item["match_score"] = score
                item["match_reason"] = reason
                all_items.append(item)

    # Trending TV
    for page in range(1, max_pages + 1):
        shows = fetch_trending_tv(page=page)
        for item in shows:
            score, reason = score_tmdb_item(item, taste)
            if score >= 0.15:
                item["match_score"] = score
                item["match_reason"] = reason
                all_items.append(item)

    # Now playing (theatrical)
    for page in range(1, max_pages + 1):
        movies = fetch_now_playing(page=page)
        for item in movies:
            score, reason = score_tmdb_item(item, taste)
            if score >= 0.15:
                item["match_score"] = score
                item["match_reason"] = reason
                all_items.append(item)

    # Sort by score
    all_items.sort(key=lambda x: x["match_score"], reverse=True)
    return all_items


def main():
    import sys
    print("[tmdb] Fetching TMDB candidates...")
    try:
        candidates = fetch_all_tmdb_candidates({}, max_pages=1)
        print(f"[tmdb] {len(candidates)} candidates fetched")
        for c in candidates[:5]:
            print(f"  • [{c.get('type','?')}] {c['title'][:45]} score={c.get('match_score',0)}")
    except RuntimeError as e:
        print(f"[tmdb] {e}")
        print("[tmdb] To use TMDB, get a free API key and run:")
        print("       echo 'YOUR_KEY' > ~/.tmdb_api_key")
        sys.exit(1)


if __name__ == "__main__":
    main()
