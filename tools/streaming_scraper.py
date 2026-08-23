#!/usr/bin/env python3
"""
Unified Streaming Service Scraper — "Be Prepared" pipeline.

Supports: Netflix, HBO Max, Paramount+, YouTube (via public data).
All scrapers fetch from public pages; no auth or API keys needed.

Output: suggestion_candidates.json in Elder Brain (merged with Apple Music).
"""

import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from bs4 import BeautifulSoup

ELDER_BRAIN = Path.home() / "elder_brain"
TASTE_PATH = ELDER_BRAIN / "taste_profile.json"
CANDIDATES_PATH = ELDER_BRAIN / "suggestion_candidates.json"
RAW_CANDIDATES_PATH = ELDER_BRAIN / "suggestion_candidates_raw.json"


def load_taste():
    if not TASTE_PATH.exists():
        return _default_taste()
    with open(TASTE_PATH) as fh:
        return json.load(fh)


def _default_taste():
    return {
        "version": 1,
        "elder_name": "Tom",
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "music": {
            "genres": ["prog-rock", "jazz", "classical", "rock"],
            "artists": ["Pink Floyd", "Charles Mingus", "Miles Davis"],
            "eras": ["1970s", "2020s"],
            "avoid": ["country", "EDM", "hip-hop/rap"]
        },
        "film": {
            "directors": ["Hayao Miyazaki", "Stanley Kubrick", "Christopher Nolan"],
            "genres": ["sci-fi", "animation", "thriller", "documentary"],
            "eras": ["1980s", "1990s", "2010s", "2020s"],
            "avoid": ["horror", "reality TV", "game shows"],
            "rewatch_favorites": ["Blade Runner", "Spirited Away", "The Godfather"]
        },
        "tv": {
            "genres": ["drama", "sci-fi", "documentary", "comedy"],
            "shows": ["The Crown", "Breaking Bad", "Planet Earth"],
            "avoid": ["reality competition", "talk shows"]
        },
        "cadence": {
            "max_suggestions_per_day": 3,
            "min_hours_between_offers": 4,
            "quiet_hours_start": "22:00",
            "quiet_hours_end": "09:00"
        },
        "sources": {
            "movietime1993_enabled": True,
            "cinegold_enabled": True,
            "select10_enabled": True,
            "darrenvandam_enabled": True,
            "rogerebert_enabled": True,
            "vulture_enabled": True,
            "apple_music_enabled": True,
            "netflix_enabled": True,
            "hbo_enabled": True,
            "paramount_enabled": True,
            "youtube_enabled": True
        }
    }


def fetch_html(url):
    """Fetch HTML with retries and UA spoofing."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"[scraper] Failed to fetch {url}: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# MOVIETIME1993 YOUTUBE SCRAPER — Action/sci-fi/historical lists
# ═══════════════════════════════════════════════════════════════

_MOVIETIME_SERVICE_MAP = {
    "netflix": "netflix",
    "apple tv": "apple_tv_plus",
    "sci-fi": "multi_service",
    "action": "multi_service",
    "historical": "multi_service",
    "thriller": "multi_service",
}


def _detect_movietime_service(title: str) -> str:
    t = title.lower()
    for keyword, service in _MOVIETIME_SERVICE_MAP.items():
        if keyword in t:
            return service
    return "multi_service"


def scrape_movietime1993():
    """Fetch latest videos from @MovieTime_1993 channel."""
    import json
    import subprocess

    channel_url = "https://www.youtube.com/@MovieTime_1993"
    try:
        result = subprocess.run(
            ["yt-dlp", "--flat-playlist", "--dump-json", "--playlist-end", "15", channel_url],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            print(f"[movietime1993] yt-dlp error: {result.stderr[:200]}")
            return []
    except Exception as e:
        print(f"[movietime1993] yt-dlp failed: {e}")
        return []

    items = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue

        title = data.get("title", "").strip()
        video_id = data.get("id", "")
        duration = data.get("duration_string", "")
        view_count = data.get("view_count", 0)

        if not title or not video_id:
            continue
        if data.get("duration", 9999) < 60:
            continue
        if data.get("live_status"):
            continue

        service = _detect_movietime_service(title)
        url = f"https://www.youtube.com/watch?v={video_id}"

        items.append({
            "type": "youtube_review",
            "title": title,
            "service": service,
            "description": f"{duration} curated list by MovieTime_1993 ({view_count:,} views)",
            "url": url,
            "channel": "MovieTime_1993",
            "duration": duration,
            "view_count": view_count,
        })

    print(f"[movietime1993] Scraped {len(items)} videos")
    return items


# ═══════════════════════════════════════════════════════════════
# CINEGOLDPRESENTS YOUTUBE SCRAPER — Curated movie list videos
# ═══════════════════════════════════════════════════════════════

_CINEGOLD_SERVICE_MAP = {
    "netflix": "netflix",
    "prime": "amazon_prime",
    "amazon": "amazon_prime",
    "apple tv": "apple_tv_plus",
    "apple tv+": "apple_tv_plus",
    "imdb": "multi_service",
    "action": "multi_service",
    "thriller": "multi_service",
    "historical": "multi_service",
    "sci-fi": "multi_service",
    "survival": "multi_service",
    "post-apocalyptic": "multi_service",
    "blockbuster": "multi_service",
}


def _detect_cinegold_service(title: str) -> str:
    t = title.lower()
    for keyword, service in _CINEGOLD_SERVICE_MAP.items():
        if keyword in t:
            return service
    return "multi_service"


def scrape_cinegold():
    """Fetch latest videos from @CineGoldPresents channel."""
    import json
    import subprocess

    channel_url = "https://www.youtube.com/@CineGoldPresents"
    try:
        result = subprocess.run(
            ["yt-dlp", "--flat-playlist", "--dump-json", "--playlist-end", "15", channel_url],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            print(f"[cinegold] yt-dlp error: {result.stderr[:200]}")
            return []
    except Exception as e:
        print(f"[cinegold] yt-dlp failed: {e}")
        return []

    items = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue

        title = data.get("title", "").strip()
        video_id = data.get("id", "")
        duration = data.get("duration_string", "")
        view_count = data.get("view_count", 0)

        if not title or not video_id:
            continue
        if data.get("duration", 9999) < 60:
            continue
        if data.get("live_status"):
            continue

        service = _detect_cinegold_service(title)
        url = f"https://www.youtube.com/watch?v={video_id}"

        items.append({
            "type": "youtube_review",
            "title": title,
            "service": service,
            "description": f"{duration} curated list by CineGoldPresents ({view_count:,} views)",
            "url": url,
            "channel": "CineGoldPresents",
            "duration": duration,
            "view_count": view_count,
        })

    print(f"[cinegold] Scraped {len(items)} videos")
    return items


# ═══════════════════════════════════════════════════════════════
# SELECT10 YOUTUBE SCRAPER — Curated TV/movie list videos
# ═══════════════════════════════════════════════════════════════

_SELECT10_SERVICE_MAP = {
    "netflix": "netflix",
    "prime": "amazon_prime",
    "amazon": "amazon_prime",
    "apple tv": "apple_tv_plus",
    "apple tv+": "apple_tv_plus",
    "apple tv plus": "apple_tv_plus",
    "imdb": "multi_service",
    "action": "multi_service",
    "sci-fi": "multi_service",
    "sci fi": "multi_service",
}


def _detect_select10_service(title: str) -> str:
    t = title.lower()
    for keyword, service in _SELECT10_SERVICE_MAP.items():
        if keyword in t:
            return service
    return "multi_service"


def scrape_select10():
    """Fetch latest videos from @Select10 channel."""
    import json
    import subprocess

    channel_url = "https://www.youtube.com/@Select10"
    try:
        result = subprocess.run(
            ["yt-dlp", "--flat-playlist", "--dump-json", "--playlist-end", "15", channel_url],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            print(f"[select10] yt-dlp error: {result.stderr[:200]}")
            return []
    except Exception as e:
        print(f"[select10] yt-dlp failed: {e}")
        return []

    items = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue

        title = data.get("title", "").strip()
        video_id = data.get("id", "")
        duration = data.get("duration_string", "")
        view_count = data.get("view_count", 0)

        if not title or not video_id:
            continue
        if data.get("duration", 9999) < 60:
            continue
        if data.get("live_status"):
            continue

        service = _detect_select10_service(title)
        url = f"https://www.youtube.com/watch?v={video_id}"

        items.append({
            "type": "youtube_review",
            "title": title,
            "service": service,
            "description": f"{duration} curated list by Select10 ({view_count:,} views)",
            "url": url,
            "channel": "Select10",
            "duration": duration,
            "view_count": view_count,
        })

    print(f"[select10] Scraped {len(items)} videos")
    return items


# ═══════════════════════════════════════════════════════════════
# DARRENVANDAM YOUTUBE SCRAPER — Streaming movie review videos
# ═══════════════════════════════════════════════════════════════

_DARRENVANDAM_SERVICE_MAP = {
    "prime": "amazon_prime",
    "amazon": "amazon_prime",
    "netflix": "netflix",
    "hbo": "hbo_max",
    "max": "hbo_max",
    "paramount": "paramount_plus",
    "tubi": "tubi",
    "youtube": "youtube_movies",
    "free": "free_streaming",
    "library": "library_of_congress",
    "taxes": "free_streaming",
    "sci-fi": "multi_service",
    "science fiction": "multi_service",
    "x-rated": "multi_service",
    "underrated": "multi_service",
    "overlooked": "multi_service",
    "stunning": "multi_service",
    "visually": "multi_service",
    "blockbuster": "multi_service",
    "cheaply": "multi_service",
    "surprisingly": "multi_service",
    "hard-to-find": "multi_service",
    "hard to find": "multi_service",
    "shockingly": "multi_service",
    "obsessed": "multi_service",
}


def _detect_service_from_title(title: str) -> str:
    t = title.lower()
    for keyword, service in _DARRENVANDAM_SERVICE_MAP.items():
        if keyword in t:
            return service
    return "multi_service"


def scrape_darrenvandam():
    """Fetch latest videos from @DarrenVanDam (Flick Connection) channel."""
    import json
    import subprocess

    channel_url = "https://www.youtube.com/@DarrenVanDam"
    try:
        result = subprocess.run(
            ["yt-dlp", "--flat-playlist", "--dump-json", "--playlist-end", "15", channel_url],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            print(f"[darrenvandam] yt-dlp error: {result.stderr[:200]}")
            return []
    except Exception as e:
        print(f"[darrenvandam] yt-dlp failed: {e}")
        return []

    items = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue

        title = data.get("title", "").strip()
        video_id = data.get("id", "")
        duration = data.get("duration_string", "")
        view_count = data.get("view_count", 0)

        if not title or not video_id:
            continue

        # Skip shorts (under 60 seconds) and non-review content
        if data.get("duration", 9999) < 60:
            continue
        # Skip live streams
        if data.get("live_status"):
            continue

        service = _detect_service_from_title(title)
        url = f"https://www.youtube.com/watch?v={video_id}"

        items.append({
            "type": "youtube_review",
            "title": title,
            "service": service,
            "description": f"{duration} streaming movie review by DarrenVanDam ({view_count:,} views)",
            "url": url,
            "channel": "Flick Connection",
            "duration": duration,
            "view_count": view_count,
        })

    print(f"[darrenvandam] Scraped {len(items)} videos")
    return items


# ═══════════════════════════════════════════════════════════════
# ROGER EBERT SCRAPER — Current film reviews
# ═══════════════════════════════════════════════════════════════

def scrape_rogerebert():
    url = "https://www.rogerebert.com/reviews"
    html = fetch_html(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    items = []

    for h3 in soup.find_all("h3"):
        text = h3.get_text(strip=True)
        if not text or len(text) < 3:
            continue

        # Find the closest review link
        review_link = None
        parent = h3.parent
        if parent and parent.name == "a":
            review_link = parent.get("href", "")
        else:
            for a in h3.find_all("a", limit=1):
                review_link = a.get("href", "")
            if not review_link:
                # Look upward for a link wrapper
                for ancestor in [h3.parent, h3.parent.parent if h3.parent else None]:
                    if ancestor and ancestor.name == "a":
                        review_link = ancestor.get("href", "")
                        break

        if review_link and not review_link.startswith("http"):
            review_link = "https://www.rogerebert.com" + review_link

        # Extract reviewer name from text if appended
        title = text
        reviewer_match = re.search(r'([A-Z][a-z]+\s[A-Z][a-z]+)$', text)
        reviewer = ""
        if reviewer_match:
            reviewer = reviewer_match.group(1)
            # Heuristic: if last two words look like a name, strip them
            if reviewer in ("Brian Tallerico", "Clint Worthington", "Simon Abrams",
                           "Matt Zoller Seitz", "Rendy Jones", "Glenn Kenny", "Cortlyn Kelly"):
                title = text[:text.rfind(reviewer)].strip()

        # Skip section headers
        if title.lower() in ("reviews", "features", "channels", "search"):
            continue

        items.append({
            "type": "film_review",
            "title": title,
            "service": "rogerebert",
            "description": f"Review by {reviewer}" if reviewer else "Film review",
            "url": review_link or "https://www.rogerebert.com/reviews",
        })

    print(f"[rogerebert] Scraped {len(items)} items")
    return items


# ═══════════════════════════════════════════════════════════════
# VULTURE SCRAPER — Best streaming recommendations
# ═══════════════════════════════════════════════════════════════

def scrape_vulture():
    urls = [
        ("https://www.vulture.com/article/best-movies-on-netflix-right-now.html", "netflix"),
        ("https://www.vulture.com/article/best-movies-on-hulu-right-now.html", "hulu"),
        ("https://www.vulture.com/article/best-movies-on-disney-plus-right-now.html", "disney_plus"),
    ]
    items = []
    for url, service in urls:
        html = fetch_html(url)
        if not html:
            continue
        soup = BeautifulSoup(html, "lxml")
        for h2 in soup.find_all("h2"):
            text = h2.get_text(strip=True)
            if not text or len(text) < 3:
                continue
            # Skip section/category headers and junk
            skip_prefixes = (
                "how we pick", "this week", "netflix movies", "more from",
                "action", "adventure", "animation", "comedy", "crime", "documentary",
                "drama", "fantasy", "horror", "mystery", "romance", "sci-fi",
                "thriller", "war", "western", "musical", "biography",
                "best ", "worst ", "ranked", "all ", "complete", "every ",
            )
            if any(text.lower().startswith(p) for p in skip_prefixes):
                continue
            # Skip if it looks like a category name (short + no punctuation + generic)
            if len(text) < 15 and text.isalpha():
                continue
            items.append({
                "type": "film",
                "title": text,
                "service": service,
                "description": f"Featured on Vulture's best {service} movies list",
                "url": url,
            })
    print(f"[vulture] Scraped {len(items)} items")
    return items


# ═══════════════════════════════════════════════════════════════
# NETFLIX SCRAPER — TVGuide h3 structure
# ═══════════════════════════════════════════════════════════════

def scrape_netflix():
    url = "https://www.tvguide.com/news/new-on-netflix/"
    html = fetch_html(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    items = []

    # TVGuide uses h3 tags with titles and dates in parentheses
    for h3 in soup.find_all("h3"):
        text = h3.get_text(strip=True)
        if not text or len(text) < 5:
            continue
        # Skip section headers
        if text.lower().startswith(("more on", "everything", "the best", "new netflix")):
            continue
        # Skip if it's just a date reference
        if text.lower().startswith("last month") or text.lower().startswith("more streaming"):
            continue

        # Extract title and date
        title = text
        release_date = ""
        date_match = re.search(r'\s*\(([A-Za-z]+\.?\s*\d+[^)]*)\)$', text)
        if date_match:
            release_date = date_match.group(1)
            title = text[:date_match.start()].strip()

        # Find description: next paragraph
        desc = ""
        next_p = h3.find_next("p")
        if next_p:
            desc = next_p.get_text(strip=True)

        items.append({
            "type": "tv_movie",
            "title": title,
            "service": "netflix",
            "description": desc[:300],
            "release_date": release_date,
            "url": "https://www.netflix.com",
        })

    print(f"[netflix] Scraped {len(items)} items")
    return items


# ═══════════════════════════════════════════════════════════════
# HBO MAX SCRAPER — TVGuide h3 structure (same pattern)
# ═══════════════════════════════════════════════════════════════

def scrape_hbo():
    url = "https://www.tvguide.com/news/new-on-max-hbo/"
    html = fetch_html(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    items = []

    for h3 in soup.find_all("h3"):
        text = h3.get_text(strip=True)
        if not text or len(text) < 5:
            continue
        if text.lower().startswith(("more on", "everything", "the best", "new hbo")):
            continue
        if text.lower().startswith("last month") or text.lower().startswith("more streaming"):
            continue

        title = text
        release_date = ""
        date_match = re.search(r'\s*\(([A-Za-z]+\.?\s*\d+[^)]*)\)$', text)
        if date_match:
            release_date = date_match.group(1)
            title = text[:date_match.start()].strip()

        desc = ""
        next_p = h3.find_next("p")
        if next_p:
            desc = next_p.get_text(strip=True)

        items.append({
            "type": "tv_movie",
            "title": title,
            "service": "hbo_max",
            "description": desc[:300],
            "release_date": release_date,
            "url": "https://www.hbomax.com",
        })

    print(f"[hbo_max] Scraped {len(items)} items")
    return items


# ═══════════════════════════════════════════════════════════════
# PARAMOUNT+ SCRAPER — TVGuide paragraph/strong date structure
# ═══════════════════════════════════════════════════════════════

def scrape_paramount():
    url = "https://www.tvguide.com/news/new-on-paramount-plus/"
    html = fetch_html(url)
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    items = []

    # Paramount uses paragraphs with <strong>date</strong> followed by titles
    # Example: "Aug. 2Lioness (Season 3) — Paramount+ Original Series"
    for p in soup.find_all("p"):
        strong = p.find("strong")
        if not strong:
            continue

        date_text = strong.get_text(strip=True)
        # Must look like a date
        if not re.match(r'^[A-Z][a-z]+\.?\s*\d+', date_text):
            continue

        # Get full paragraph text, remove the strong date part
        full_text = p.get_text(strip=True)
        remaining = full_text.replace(date_text, "", 1).strip()

        # Sometimes titles are all run together, try to split on capital letters
        # or known patterns. For now, use the remaining text as description/title
        if not remaining or len(remaining) < 3:
            continue

        # Skip if it looks like a notice/disclaimer
        if remaining.lower().startswith(("available", "*available")):
            continue

        items.append({
            "type": "tv_movie",
            "title": remaining[:100],
            "service": "paramount_plus",
            "description": remaining[:300],
            "release_date": date_text,
            "url": "https://www.paramountplus.com",
        })

    print(f"[paramount_plus] Scraped {len(items)} items")
    return items


# ═══════════════════════════════════════════════════════════════
# YOUTUBE SCRAPER — trending music videos
# ═══════════════════════════════════════════════════════════════

def scrape_youtube():
    """Scrape YouTube trending music via RSS where available."""
    url = "https://www.youtube.com/feed/trending?gl=US"
    html = fetch_html(url)
    if not html:
        return []

    # Extract video titles from trending page
    titles = re.findall(r'\"title\":\s*{\s*\"runs\":\s*\[\s*{\s*\"text\":\s*\"([^\"]+)\"', html)

    items = []
    for title in titles[:20]:
        if len(title) < 3:
            continue
        items.append({
            "type": "video",
            "title": title,
            "service": "youtube",
            "description": "",
            "url": f"https://www.youtube.com/results?search_query={urllib.request.quote(title)}",
        })

    print(f"[youtube] Scraped {len(items)} trending items")
    return items


# ═══════════════════════════════════════════════════════════════
# SCORING ENGINE
# ═══════════════════════════════════════════════════════════════

def score_film_item(item, taste):
    """Score a film/TV item against taste profile."""
    film = taste.get("film", {})
    tv = taste.get("tv", {})
    fav_directors = [d.lower() for d in film.get("directors", [])]
    fav_genres = [g.lower() for g in film.get("genres", []) + tv.get("genres", [])]
    avoid = [a.lower() for a in film.get("avoid", []) + tv.get("avoid", [])]
    fav_shows = [s.lower() for s in tv.get("shows", [])]

    title = item.get("title", "").lower()
    desc = item.get("description", "").lower()

    # Rejections
    if any(a in title or a in desc for a in avoid):
        return 0.0, "avoided"

    score = 0.0
    reasons = []

    # Genre match (check both title/description AND explicit genre list)
    item_genres = [g.lower() for g in item.get("genres", [])]
    if item_genres:
        genre_hits = sum(1 for g in item_genres if any(fav in g for fav in fav_genres))
        if genre_hits:
            score += min(0.3 + genre_hits * 0.1, 0.6)
            reasons.append("matching_genre")
    elif any(g in title or g in desc for g in fav_genres):
        score += 0.3
        reasons.append("matching_genre")

    # Director match
    if any(d in title or d in desc for d in fav_directors):
        score += 0.6
        reasons.append("favorite_director")

    # Show/franchise match
    if any(s in title or s in desc for s in fav_shows):
        score += 0.5
        reasons.append("related_show")

    # Era hint (decade in title or year field)
    eras = film.get("eras", [])
    year = item.get("year", "")
    era_text = f"{title} {year}"
    if any(e[:3] in era_text for e in eras):
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


def build_all_candidates(taste):
    """Run all enabled scrapers and merge results."""
    all_candidates = []
    sources = taste.get("sources", {})

    # TMDB enrichment (best data, if API key available)
    try:
        from tmdb_client import fetch_all_tmdb_candidates
        print("[scraper] Fetching from TMDB...")
        tmdb_candidates = fetch_all_tmdb_candidates(taste, max_pages=2)
        print(f"[scraper] TMDB returned {len(tmdb_candidates)} candidates")
        all_candidates.extend(tmdb_candidates)
    except Exception as e:
        print(f"[scraper] TMDB unavailable ({e}), trying IMDb datasets...")
        try:
            from imdb_dataset import fetch_imdb_candidates
            imdb_candidates = fetch_imdb_candidates(taste, max_results=100, recent_only=True)
            print(f"[scraper] IMDb returned {len(imdb_candidates)} candidates")
            all_candidates.extend(imdb_candidates)
        except Exception as e2:
            print(f"[scraper] IMDb also failed ({e2}), trying free sources...")
            try:
                from free_movie_sources import fetch_all_candidates as fetch_free
                free_candidates = fetch_free(taste, max_per_source=50)
                print(f"[scraper] Free sources returned {len(free_candidates)} candidates")
                all_candidates.extend(free_candidates)
            except Exception as e3:
                print(f"[scraper] All enrichment failed ({e3}), continuing with basic scrapers")

    if sources.get("netflix_enabled", False):
        netflix = scrape_netflix()
        for item in netflix:
            score, reason = score_film_item(item, taste)
            if score >= 0.2:
                item["match_score"] = score
                item["match_reason"] = reason
                all_candidates.append(item)

    if sources.get("hbo_enabled", False):
        hbo = scrape_hbo()
        for item in hbo:
            score, reason = score_film_item(item, taste)
            if score >= 0.2:
                item["match_score"] = score
                item["match_reason"] = reason
                all_candidates.append(item)

    if sources.get("paramount_enabled", False):
        paramount = scrape_paramount()
        for item in paramount:
            score, reason = score_film_item(item, taste)
            if score >= 0.1:
                item["match_score"] = score
                item["match_reason"] = reason
                all_candidates.append(item)

    if sources.get("youtube_enabled", False):
        youtube = scrape_youtube()
        for item in youtube:
            score, reason = score_film_item(item, taste)
            if score >= 0.1:
                item["match_score"] = score
                item["match_reason"] = reason
                all_candidates.append(item)

    if sources.get("movietime1993_enabled", False):
        mt = scrape_movietime1993()
        for item in mt:
            score, reason = score_film_item(item, taste)
            if score >= 0.1:
                item["match_score"] = score
                item["match_reason"] = reason
                all_candidates.append(item)

    if sources.get("cinegold_enabled", False):
        cg = scrape_cinegold()
        for item in cg:
            score, reason = score_film_item(item, taste)
            if score >= 0.1:
                item["match_score"] = score
                item["match_reason"] = reason
                all_candidates.append(item)

    if sources.get("select10_enabled", False):
        s10 = scrape_select10()
        for item in s10:
            score, reason = score_film_item(item, taste)
            if score >= 0.1:
                item["match_score"] = score
                item["match_reason"] = reason
                all_candidates.append(item)

    if sources.get("darrenvandam_enabled", False):
        dv = scrape_darrenvandam()
        for item in dv:
            score, reason = score_film_item(item, taste)
            if score >= 0.1:
                item["match_score"] = score
                item["match_reason"] = reason
                all_candidates.append(item)

    if sources.get("rogerebert_enabled", False):
        rogerebert = scrape_rogerebert()
        for item in rogerebert:
            score, reason = score_film_item(item, taste)
            if score >= 0.1:
                item["match_score"] = score
                item["match_reason"] = reason
                all_candidates.append(item)

    if sources.get("vulture_enabled", False):
        vulture = scrape_vulture()
        for item in vulture:
            score, reason = score_film_item(item, taste)
            if score >= 0.1:
                item["match_score"] = score
                item["match_reason"] = reason
                all_candidates.append(item)

    # Sort by score
    all_candidates.sort(key=lambda x: x["match_score"], reverse=True)
    return all_candidates


def merge_with_existing(candidates):
    """Merge with existing Apple Music candidates if present."""
    if CANDIDATES_PATH.exists():
        try:
            with open(CANDIDATES_PATH) as fh:
                existing = json.load(fh)
            existing_candidates = existing.get("candidates", [])
            seen = set()
            merged = []
            for c in existing_candidates + candidates:
                key = f"{c['title']}:{c.get('service','unknown')}".lower()
                if key not in seen:
                    seen.add(key)
                    merged.append(c)
            merged.sort(key=lambda x: x.get("match_score", 0), reverse=True)
            return merged
        except Exception:
            pass
    return candidates


def write_candidates(candidates):
    # Save raw candidates for availability_filter.py
    raw_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": ["imdb", "tmdb", "netflix", "hbo_max", "paramount_plus", "youtube", "rogerebert", "vulture"],
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
    ELDER_BRAIN.mkdir(parents=True, exist_ok=True)
    with open(RAW_CANDIDATES_PATH, "w") as fh:
        json.dump(raw_payload, fh, indent=2)
    print(f"[scraper] Wrote {len(candidates)} raw candidates to {RAW_CANDIDATES_PATH}")

    # Also save as main output for backward compat
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": ["imdb", "tmdb", "netflix", "hbo_max", "paramount_plus", "youtube", "rogerebert", "vulture"],
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
    with open(CANDIDATES_PATH, "w") as fh:
        json.dump(payload, fh, indent=2)
    print(f"[scraper] Wrote {len(candidates)} total candidates to {CANDIDATES_PATH}")


def main():
    print("[scraper] Loading taste profile...")
    taste = load_taste()

    print("[scraper] Running all streaming scrapers...")
    candidates = build_all_candidates(taste)
    print(f"[scraper] {len(candidates)} new candidates matched taste")

    merged = merge_with_existing(candidates)
    print(f"[scraper] {len(merged)} total after merge/dedupe")

    write_candidates(merged)

    # Show top 10
    for c in merged[:10]:
        print(f"  • [{c.get('service','?')}] {c['title'][:50]} score={c.get('match_score',0)} ({c.get('match_reason','')})")


if __name__ == "__main__":
    main()
