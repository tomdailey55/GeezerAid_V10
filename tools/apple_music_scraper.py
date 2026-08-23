#!/usr/bin/env python3
"""
Apple Music New Release Scraper — "Be Prepared" pipeline.

Uses the public iTunes Store RSS feed for top albums (no auth needed):
  https://itunes.apple.com/us/rss/topalbums/limit=200/json

Cross-references with taste_profile.json to build suggestion_candidates.json.

To upgrade to the official Apple Music API later:
  1. Generate a MusicKit private key at https://developer.apple.com/account/resources/
  2. Sign a JWT developer token
  3. Switch endpoint to https://api.music.apple.com/v1/catalog/us/new-releases
"""

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ──
ELDER_BRAIN = Path.home() / "elder_brain"
TASTE_PATH = ELDER_BRAIN / "taste_profile.json"
CANDIDATES_PATH = ELDER_BRAIN / "suggestion_candidates.json"

# ── RSS Feed (public, no auth) ──
ITUNES_TOP_ALBUMS = "https://itunes.apple.com/us/rss/topalbums/limit=200/json"


def load_taste_profile():
    if not TASTE_PATH.exists():
        return _default_taste()
    with open(TASTE_PATH) as fh:
        return json.load(fh)


def _default_taste():
    """Seed profile — editable by user or extracted from conversations."""
    return {
        "version": 1,
        "elder_name": "Tom",
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "music": {
            "genres": ["prog-rock", "jazz", "classical", "rock"],
            "artists": ["Pink Floyd", "Charles Mingus", "Kamasi Washington", "Miles Davis"],
            "eras": ["1970s", "2020s"],
            "avoid": ["country", "EDM", "hip-hop/rap"]
        },
        "film": {
            "directors": ["Hayao Miyazaki", "Stanley Kubrick", "Steven Spielberg",
                         "Martin Scorsese", "Clint Eastwood", "Christopher Nolan",
                         "Ridley Scott", "Denis Villeneuve"],
            "genres": ["sci-fi", "animation", "drama", "thriller", "documentary",
                       "mystery", "historical", "biography", "war", "western"],
            "eras": ["1980s", "1990s", "2000s", "2010s", "2020s"],
            "avoid": ["horror", "reality TV", "game shows", "excessive violence",
                     "graphic content", "superhero"],
            "rewatch_favorites": ["Blade Runner", "Spirited Away", "The Godfather",
                                 "Schindler's List", "Saving Private Ryan",
                                 "The Shawshank Redemption", "Forrest Gump"]
        },
        "tv": {
            "genres": ["drama", "sci-fi", "documentary", "comedy", "mystery",
                      "crime", "period drama", "political drama"],
            "shows": ["The Crown", "Breaking Bad", "Planet Earth", "The West Wing",
                     "Downton Abbey", "Midsomer Murders", "Vera", "Poirot",
                     "Sherlock", "Line of Duty", "Succession", "Yellowstone"],
            "avoid": ["reality competition", "talk shows", "game shows", "soap opera"]
        },
        "cadence": {
            "max_suggestions_per_day": 3,
            "min_hours_between_offers": 4,
            "quiet_hours_start": "22:00",
            "quiet_hours_end": "09:00"
        },
        "sources": {"apple_music_enabled": True, "netflix_enabled": True}
    }


def fetch_top_albums():
    """Pull top albums from public iTunes RSS."""
    req = urllib.request.Request(
        ITUNES_TOP_ALBUMS,
        headers={"Accept": "application/json", "User-Agent": "GeezerAid/1.0"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    entries = data.get("feed", {}).get("entry", [])
    albums = []
    for e in entries:
        album = _parse_entry(e)
        if album:
            albums.append(album)
    return albums


def _parse_entry(e):
    """Extract fields from iTunes RSS entry."""
    name_node = e.get("im:name", {})
    title = name_node.get("label", "") if isinstance(name_node, dict) else ""

    artist_node = e.get("im:artist", {})
    artist = artist_node.get("label", "") if isinstance(artist_node, dict) else ""
    artist_link = artist_node.get("attributes", {}).get("href", "") if isinstance(artist_node, dict) else ""

    cat_node = e.get("category", {})
    genre = cat_node.get("attributes", {}).get("label", "") if isinstance(cat_node, dict) else ""
    genre_term = cat_node.get("attributes", {}).get("term", "") if isinstance(cat_node, dict) else ""

    rd_node = e.get("im:releaseDate", {})
    release_date = rd_node.get("label", "") if isinstance(rd_node, dict) else ""
    year = release_date[:4] if release_date else ""

    # Find album link
    album_url = ""
    links = e.get("link", [])
    if isinstance(links, list):
        for l in links:
            if isinstance(l, dict):
                attrs = l.get("attributes", {})
                if attrs.get("type", "").startswith("audio/x-m4a"):
                    album_url = attrs.get("href", "")
                    break
    if not album_url and isinstance(links, dict):
        album_url = links.get("attributes", {}).get("href", "")

    # Build Apple Music link if we only have iTunes preview
    if not album_url and artist_link:
        # Try to construct from artist link pattern
        album_url = artist_link.replace("?uo=2", "")

    if not title or not artist:
        return None

    return {
        "type": "music_album",
        "service": "apple_music",
        "title": title,
        "artist": artist,
        "genre": genre,
        "genre_term": genre_term,
        "url": album_url,
        "year": year,
        "release_date": release_date,
    }


def score_candidate(album, taste):
    """
    Score 0.0-1.0 based on taste_profile overlap.
    Returns (score, reason_string).
    """
    music = taste.get("music", {})
    fav_artists = [a.lower() for a in music.get("artists", [])]
    fav_genres = [g.lower() for g in music.get("genres", [])]
    avoid_genres = [g.lower() for g in music.get("avoid", [])]

    artist = album.get("artist", "").lower()
    genre = album.get("genre", "").lower()
    genre_term = album.get("genre_term", "").lower()

    # Immediate reject
    combined_genre = f"{genre} {genre_term}"
    if any(avoid in combined_genre for avoid in avoid_genres):
        return 0.0, "avoided_genre"

    score = 0.0
    reasons = []

    # Artist match (strong signal)
    if any(fav in artist for fav in fav_artists):
        score += 0.6
        reasons.append("favorite_artist")

    # Genre match
    if any(fav in combined_genre for fav in fav_genres):
        score += 0.3
        reasons.append("matching_genre")

    # Era match (rough year match)
    year = album.get("year", "")
    eras = music.get("eras", [])
    if year and any(year.startswith(e[:2]) for e in eras):
        score += 0.1
        reasons.append("era_match")

    return round(min(score, 1.0), 2), ",".join(reasons) if reasons else "no_match"


def build_candidates(albums, taste, min_score=0.3):
    """Filter and score albums into suggestion candidates."""
    candidates = []
    seen = set()
    for alb in albums:
        key = f"{alb['artist']}:{alb['title']}".lower()
        if key in seen:
            continue
        seen.add(key)
        score, reason = score_candidate(alb, taste)
        if score >= min_score:
            candidates.append({
                **alb,
                "match_score": score,
                "match_reason": reason,
            })
    # Sort by score desc
    candidates.sort(key=lambda x: x["match_score"], reverse=True)
    return candidates


def write_candidates(candidates):
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "itunes_topalbums_rss",
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
    ELDER_BRAIN.mkdir(parents=True, exist_ok=True)
    with open(CANDIDATES_PATH, "w") as fh:
        json.dump(payload, fh, indent=2)
    print(f"[scraper] Wrote {len(candidates)} candidates to {CANDIDATES_PATH}")


def main():
    print("[scraper] Loading taste profile...")
    taste = load_taste_profile()

    print("[scraper] Fetching iTunes top albums...")
    albums = fetch_top_albums()
    print(f"[scraper] Got {len(albums)} raw albums")

    print("[scraper] Scoring against taste profile...")
    candidates = build_candidates(albums, taste)
    print(f"[scraper] {len(candidates)} matched taste (score >= 0.3)")

    write_candidates(candidates)

    # Print top 5 for visibility
    for c in candidates[:5]:
        print(f"  • {c['artist']} — '{c['title']}' [{c['genre']}] score={c['match_score']} ({c['match_reason']})")


if __name__ == "__main__":
    main()
