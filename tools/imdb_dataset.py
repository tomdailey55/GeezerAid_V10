#!/usr/bin/env python3
"""
IMDb Dataset Client — public data files, no API key, no scraping.

IMDb releases monthly .tsv.gz dumps:
  https://datasets.imdbws.com/

Key files:
  - title.basics.tsv.gz  → title, type, year, genres, runtime
  - title.ratings.tsv.gz → averageRating, numVotes
  - title.akas.tsv.gz    → regional titles (US, UK)

All local queries after download. Fast, no rate limits, no signup.
"""

import gzip
import json
import math
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path.home() / ".cache" / "geezeraid" / "imdb_datasets"
DATASETS = {
    "basics": "https://datasets.imdbws.com/title.basics.tsv.gz",
    "ratings": "https://datasets.imdbws.com/title.ratings.tsv.gz",
}

# Cache datasets for 7 days
DATASET_MAX_AGE_DAYS = 7


def _download_if_stale(name, url):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"{name}.tsv.gz"
    txt_path = DATA_DIR / f"{name}.tsv"

    # Check age
    needs_download = True
    if path.exists():
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        age_days = (datetime.now(timezone.utc) - mtime).days
        if age_days < DATASET_MAX_AGE_DAYS:
            needs_download = False
            print(f"[imdb] {name}: using cached ({age_days}d old)")

    if needs_download:
        print(f"[imdb] Downloading {name}...")
        req = urllib.request.Request(url, headers={"User-Agent": "GeezerAid/1.0"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            with open(path, "wb") as fh:
                fh.write(resp.read())
        print(f"[imdb] {name}: downloaded ({path.stat().st_size // 1024 // 1024}MB)")

    # Decompress if needed
    if not txt_path.exists() or path.stat().st_mtime > txt_path.stat().st_mtime:
        print(f"[imdb] Decompressing {name}...")
        with gzip.open(path, "rt", encoding="utf-8") as gz:
            with open(txt_path, "w", encoding="utf-8") as out:
                out.write(gz.read())

    return txt_path


def _parse_tsv_line(line):
    """Split TSV line respecting quoted fields."""
    return line.strip().split("\t")


def load_basics():
    """Yield dicts from title.basics."""
    path = _download_if_stale("basics", DATASETS["basics"])
    with open(path, "r", encoding="utf-8") as fh:
        headers = fh.readline().strip().split("\t")
        for line in fh:
            parts = _parse_tsv_line(line)
            if len(parts) < len(headers):
                continue
            yield dict(zip(headers, parts))


def load_ratings():
    """Load ratings into a dict keyed by tconst."""
    path = _download_if_stale("ratings", DATASETS["ratings"])
    ratings = {}
    with open(path, "r", encoding="utf-8") as fh:
        headers = fh.readline().strip().split("\t")
        for line in fh:
            parts = _parse_tsv_line(line)
            if len(parts) < len(headers):
                continue
            row = dict(zip(headers, parts))
            try:
                ratings[row["tconst"]] = {
                    "rating": float(row["averageRating"]),
                    "votes": int(row["numVotes"]),
                }
            except (ValueError, KeyError):
                continue
    return ratings


# Simple title-to-genre inference for IMDb genres
GENRE_BOOST = {
    "sci-fi": ["sci-fi", "science fiction"],
    "animation": ["animation", "anime"],
    "drama": ["drama"],
    "thriller": ["thriller", "mystery"],
    "documentary": ["documentary"],
    "war": ["war"],
    "western": ["western"],
    "biography": ["biography"],
    "history": ["history", "historical"],
    "musical": ["musical", "music"],
    "romance": ["romance"],
    "adventure": ["adventure"],
    "mystery": ["mystery"],
    "crime": ["crime"],
    "film-noir": ["film noir", "noir"],
    "fantasy": ["fantasy"],
    "sport": ["sports"],
    "family": ["family"],
    "comedy": ["comedy"],
    "action": ["action"],
}


def score_imdb_row(row, taste, ratings_map):
    """Score an IMDb basics row against taste."""
    film = taste.get("film", {})
    tv = taste.get("tv", {})
    fav_genres = [g.lower() for g in film.get("genres", []) + tv.get("genres", [])]
    avoid = [a.lower() for a in film.get("avoid", []) + tv.get("avoid", [])]

    title = row.get("primaryTitle", "").lower()
    title_type = row.get("titleType", "")
    genres_str = row.get("genres", "")
    year_str = row.get("startYear", "")

    # Skip non-movie/TV
    if title_type not in ("movie", "tvMovie", "tvSeries", "tvMiniSeries", "tvEpisode"):
        return 0.0, None

    # Parse genres
    genres = [g.strip().lower() for g in genres_str.split(",") if g.strip()]

    # Avoid list
    combined = f"{title} {genres_str.lower()}"
    if any(a in combined for a in avoid):
        return 0.0, None

    score = 0.0
    reasons = []

    # Genre match (low weight — drama/mystery hit almost everything)
    genre_hits = 0
    broad_genres = {"drama", "comedy", "thriller"}  # de-weight these
    for g in genres:
        for fav in fav_genres:
            if fav in g or g in fav:
                if g not in broad_genres:
                    genre_hits += 2  # specific genres count more
                else:
                    genre_hits += 1
                break
    if genre_hits:
        score += min(0.15 + genre_hits * 0.05, 0.35)
        reasons.append("matching_genre")

    # Popularity / vote-count gate
    tconst = row.get("tconst", "")
    vote_count = 0
    if tconst in ratings_map:
        vote_count = ratings_map[tconst].get("votes", 0)
    if title_type in ("movie", "tvMovie") and vote_count < 2000:
        return 0.0, None  # Too obscure — skip
    if title_type in ("tvSeries", "tvMiniSeries") and vote_count < 1000:
        return 0.0, None

    # Rating gate — require decent quality
    rating_val = ratings_map.get(tconst, {}).get("rating", 0)
    if rating_val < 6.0 and vote_count < 10000:
        return 0.0, None  # Low-rated AND not popular = skip

    # Rating bonus (one-time)
    if rating_val >= 8.0:
        score += 0.10
        reasons.append("highly_rated")
    elif rating_val >= 7.0:
        score += 0.05
        reasons.append("well_rated")
    elif rating_val >= 6.0:
        score += 0.02
        reasons.append("decent_rated")

    # Era (weak tiebreaker)
    eras = film.get("eras", [])
    if year_str and year_str != "\\N" and any(year_str.startswith(e[:2]) for e in eras):
        score += 0.02
        reasons.append("era_hint")

    # Minimum threshold
    if score < 0.15:
        return 0.0, None

    item = {
        "type": "tv_show" if title_type in ("tvSeries", "tvMiniSeries") else "movie",
        "service": "imdb_top" if (tconst in ratings_map and ratings_map[tconst].get("votes", 0) > 50000) else "imdb",
        "title": row.get("primaryTitle", ""),
        "description": f"{title_type}, {genres_str}",
        "year": year_str if year_str != "\\N" else "",
        "release_date": year_str if year_str != "\\N" else "",
        "genres": genres,
        "vote_average": ratings_map.get(tconst, {}).get("rating", 0),
        "url": f"https://www.imdb.com/title/{tconst}/",
        "imdb_id": tconst,
    }

    return round(min(score, 1.0), 2), item


def fetch_imdb_candidates(taste, max_results=200, recent_only=True):
    """
    Query IMDb datasets and return scored candidates.

    Args:
        taste: taste profile dict
        max_results: max candidates to return
        recent_only: if True, only films from 1980+
    """
    print("[imdb] Loading ratings...")
    ratings_map = load_ratings()
    print(f"[imdb] {len(ratings_map):,} ratings loaded")

    print("[imdb] Scanning titles...")
    candidates = []
    count = 0

    for row in load_basics():
        count += 1
        if count % 500000 == 0:
            print(f"[imdb] Scanned {count:,} titles...")

        # Recent only filter
        if recent_only:
            year = row.get("startYear", "")
            if year == "\\N" or not year.isdigit() or int(year) < 1980:
                continue

        score, item = score_imdb_row(row, taste, ratings_map)
        if score > 0 and item:
            item["match_score"] = score
            item["match_reason"] = ",".join(
                [r for r in ["matching_genre", "era_hint", "highly_rated", "decent_rated"] if r in item.get("match_reason", "")]
            ) or "imdb_match"
            candidates.append(item)

        if len(candidates) >= max_results * 3:
            break

    print(f"[imdb] Scanned {count:,} titles, {len(candidates)} matched")

    # Sort by score
    candidates.sort(key=lambda x: x["match_score"], reverse=True)
    return candidates[:max_results]


def main():
    print("[imdb] Fetching candidates from public datasets...")
    taste = {
        "film": {
            "genres": ["sci-fi", "animation", "drama", "thriller", "documentary",
                       "mystery", "historical", "biography", "war", "western"],
            "eras": ["1980s", "1990s", "2000s", "2010s", "2020s"],
            "avoid": ["horror", "reality TV", "game shows", "excessive violence",
                     "graphic content", "superhero"],
        },
        "tv": {
            "genres": ["drama", "sci-fi", "documentary", "comedy", "mystery",
                      "crime", "period drama", "political drama"],
            "avoid": ["reality competition", "talk shows", "game shows", "soap opera"],
        }
    }

    candidates = fetch_imdb_candidates(taste, max_results=50, recent_only=True)
    print(f"\n[imdb] Top {len(candidates)} candidates:")
    for c in candidates[:10]:
        print(f"  • {c['title'][:40]:40s} ({c.get('year','?')}) score={c['match_score']:.2f} rating={c.get('vote_average',0)}")


if __name__ == "__main__":
    main()
