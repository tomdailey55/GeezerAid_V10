#!/usr/bin/env python3
"""GA-V9 search-driven video recommendation source (2026-08-12).

Discovery by YouTube SEARCH instead of a fixed channel list. For each owner
(Andrea, Tom), generate simple broad search queries from their viewing history
(taste_profile.json + viewing_affinity_{owner}.json), run `yt-dlp ytsearch8:`,
filter noise, and emit owner-tagged candidates.

This is ADDITIVE to streaming_scraper.py's fixed-channel scrapers — it feeds
the same suggestion_candidates.json so suggestion_engine.py's affinity re-rank
and cadence gates apply unchanged.

Cadence: intended to run WEEKLY (a cron/launchd job), not every poll.

Design notes:
  - Queries must be SIMPLE + BROAD ("best sci-fi shows", "PBS top series").
    Natural-language phrasing ("highest rated series on PBS") returns too few
    results — yt-dlp search prefers short keyword queries.
  - Results are YouTube curated-list / review videos, the same "type" GA
    already surfaces from the fixed channels.
  - LOCAL-ONLY: yt-dlp queries go to YouTube (public search); no personal data
    leaves the MBP. Results stay in elder_brain/.
  - Per-owner: Andrea's queries derive from HER viewing (PBS/drama), Tom's from
    his — matching the per-user recommendation design.

Usage:
    python3 search_candidates.py            # build for all owners, write file
    python3 search_candidates.py --owner tom  # only one owner
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ELDER_BRAIN = Path.home() / "elder_brain"
TASTE_PATH = ELDER_BRAIN / "taste_profile.json"
OUT_PATH = ELDER_BRAIN / "search_candidates.json"
YTDLP = "/opt/homebrew/bin/yt-dlp"
RESULTS_PER_QUERY = 8
QUERIES_PER_OWNER = 4

# Query templates built from (genre, service, era, show) tokens found in an
# owner's taste/affinity. Kept simple and broad for search recall.
_GENRE_QUERIES = [
    "best {g} shows",
    "best {g} movies",
    "top {g} series",
    "hidden gem {g}",
]
_SERVICE_QUERIES = [
    "{s} best shows",
    "best series on {s}",
    "top rated {s} shows",
]
_SHOW_QUERIES = [
    "shows like {show}",
    "similar to {show}",
    "best shows like {show}",
]
_ERA_QUERIES = [
    "best {e} movies",
    "{e} classic movies",
]

# Channels/topics that are kids content or noise — filter out.
_NOISE_TITLE = re.compile(
    r"\b(kids|children|for kids|pbs kids|cartoon|cartoons|minecraft|roblox|"
    r"gaming|gameplay|unboxing|asmr|compilation of|best of the week)\b",
    re.IGNORECASE,
)


def _load_json(path):
    if path.exists():
        try:
            with open(path) as fh:
                return json.load(fh)
        except Exception:
            pass
    return {}


def _load_affinity(owner):
    return _load_json(ELDER_BRAIN / f"viewing_affinity_{owner}.json")


def _tokens(profile, key):
    out = []
    for section in ("film", "tv", "music"):
        out.extend((profile.get(section) or {}).get(key, []))
    # de-dup, drop empties/short
    seen = set()
    clean = []
    for t in out:
        t = (t or "").strip()
        if t and len(t) > 2 and t.lower() not in seen:
            seen.add(t.lower())
            clean.append(t)
    return clean


def generate_queries(owner):
    """Build simple broad search queries for an owner from taste + affinity.

    PRIORITIZES per-owner data:
      1. Shows from the shared taste profile (which lists the owner's actual
         PBS/streaming shows like Downton Abbey, Grantchester).
      2. Services from the owner's app_affinity (PBS, Prime Video, ...).
      3. Falls back to shared-profile genres/eras only when the above are thin.
    This keeps Andrea's queries on PBS/period-drama, Tom's on his genres, etc.
    """
    profile = _load_json(TASTE_PATH)
    aff = _load_affinity(owner)

    shows = _tokens(profile, "shows")           # Downton Abbey, Grantchester, ...
    genres = _tokens(profile, "genres")
    eras = _tokens(profile, "eras")

    # Services the owner actually watches, ranked by event count.
    app_aff = aff.get("app_affinity") or {}
    services = [s for s, _ in sorted(app_aff.items(), key=lambda kv: -kv[1])]
    service_hints = [s.lower() for s in services if s.lower() in (
        "netflix", "hbo max", "max", "paramount plus", "amazon prime",
        "prime video", "youtube", "pbs", "apple tv", "apple tv plus",
        "hulu", "disney plus")]

    queries = []
    # 1. Show-based (strongest signal for PBS period drama fans).
    for show in shows[:4]:
        for tpl in _SHOW_QUERIES:
            queries.append(tpl.format(show=show))
    # 2. Service-based (PBS, Prime Video for Andrea).
    for s in service_hints[:2]:
        for tpl in _SERVICE_QUERIES:
            queries.append(tpl.format(s=s.replace(" ", "")))
    # 3. Genre/era fallback.
    for g in genres[:3]:
        for tpl in _GENRE_QUERIES:
            queries.append(tpl.format(g=g))
    for e in eras[:2]:
        for tpl in _ERA_QUERIES:
            queries.append(tpl.format(e=e))

    # De-dup, then BLEND so each owner gets show + service + genre coverage
    # (not just the first category to fill the cap). Interleave by source type.
    seen, by_kind = set(), {"show": [], "service": [], "genre": [], "era": []}
    for q, kind in (
        [(tpl.format(show=show), "show") for show in shows[:4] for tpl in _SHOW_QUERIES]
        + [(tpl.format(s=s.replace(" ", "")), "service") for s in service_hints[:2] for tpl in _SERVICE_QUERIES]
        + [(tpl.format(g=g), "genre") for g in genres[:3] for tpl in _GENRE_QUERIES]
        + [(tpl.format(e=e), "era") for e in eras[:2] for tpl in _ERA_QUERIES]
    ):
        q = q.strip()
        if q and q.lower() not in seen:
            seen.add(q.lower())
            by_kind[kind].append(q)
    # Round-robin across kinds so the cap isn't dominated by one category.
    clean = []
    for i in range(QUERIES_PER_OWNER):
        for kind in ("show", "service", "genre", "era"):
            if by_kind[kind]:
                clean.append(by_kind[kind].pop(0))
            if len(clean) >= QUERIES_PER_OWNER:
                break
        if len(clean) >= QUERIES_PER_OWNER:
            break
    # Fallback if profile is empty (no taste data yet).
    if not clean:
        clean = ["best shows", "best movies", "top rated series", "hidden gem movies"]
    return clean


def _detect_service(title):
    t = title.lower()
    for kw, svc in [
        ("netflix", "netflix"), ("hbo", "hbo_max"), ("max", "hbo_max"),
        ("paramount", "paramount_plus"), ("prime", "amazon_prime"),
        ("amazon", "amazon_prime"), ("apple tv", "apple_tv_plus"),
        ("pbs", "pbs"), ("hulu", "hulu"), ("disney", "disney_plus"),
        ("youtube", "youtube"),
    ]:
        if kw in t:
            return svc
    return "multi_service"


def search_query(query, n=RESULTS_PER_QUERY):
    """Run a YouTube search, return parsed video dicts (noise-filtered)."""
    try:
        r = subprocess.run(
            [YTDLP, "--flat-playlist", "--dump-json", "--playlist-end", str(n),
             f"ytsearch{n}:{query}"],
            capture_output=True, text=True, timeout=90,
        )
    except Exception as e:
        print(f"[search] yt-dlp error for '{query}': {e}")
        return []
    if r.returncode != 0:
        return []

    items = []
    for line in r.stdout.strip().splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        title = d.get("title", "").strip()
        video_id = d.get("id", "")
        duration = d.get("duration", 9999)
        if not title or not video_id:
            continue
        if duration and duration < 60:  # skip Shorts
            continue
        if d.get("live_status"):
            continue
        if _NOISE_TITLE.search(title):
            continue
        items.append({
            "type": "youtube_review",
            "title": title,
            "service": _detect_service(title),
            "description": f"curated list from search '{query}' ({d.get('channel','')})",
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "channel": d.get("channel", ""),
            "duration": d.get("duration_string", ""),
            "source": "yt_search",
        })
    return items


def build_for_owner(owner):
    queries = generate_queries(owner)
    items = []
    for q in queries:
        hits = search_query(q)
        for it in hits:
            it["owner"] = owner
            it["query"] = q
            it["match_score"] = 0.4  # search-matched; affinity re-rank happens later
            it["match_reason"] = "search_query"
        items.extend(hits)
        print(f"[search] '{q}' -> {len(hits)} items (owner={owner})")
    return items


def _merge_into_candidates(all_items):
    """Merge owner-tagged search candidates into suggestion_candidates.json
    (what suggestion_engine.py reads), deduped by title+service. Keeps the
    existing fixed-channel candidates and the search candidates together."""
    cand_path = ELDER_BRAIN / "suggestion_candidates.json"
    existing = []
    if cand_path.exists():
        try:
            with open(cand_path) as fh:
                existing = json.load(fh).get("candidates", [])
        except Exception:
            pass
    seen = set()
    merged = []
    for c in existing + all_items:
        key = f"{c.get('title','')}:{c.get('service','unknown')}".lower()
        if key not in seen:
            seen.add(key)
            merged.append(c)
    merged.sort(key=lambda x: x.get("match_score", 0), reverse=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidate_count": len(merged),
        "candidates": merged,
    }
    ELDER_BRAIN.mkdir(parents=True, exist_ok=True)
    with open(cand_path, "w") as fh:
        json.dump(payload, fh, indent=2)
    print(f"[search] Merged {len(all_items)} search candidates -> "
          f"{cand_path} ({len(merged)} total)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner", default=None, help="build for one owner only")
    ap.add_argument("--no-merge", action="store_true",
                    help="write search_candidates.json only, don't merge into main")
    args = ap.parse_args()

    owners = [args.owner] if args.owner else ["tom", "andrea"]
    all_items = []
    for owner in owners:
        all_items.extend(build_for_owner(owner))

    ELDER_BRAIN.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cadence": "weekly",
        "source": "yt_search",
        "owners": owners,
        "candidate_count": len(all_items),
        "candidates": all_items,
    }
    with open(OUT_PATH, "w") as fh:
        json.dump(payload, fh, indent=2)
    print(f"[search] Wrote {len(all_items)} candidates to {OUT_PATH}")
    for it in all_items[:10]:
        print(f"  • [{it.get('owner')}] [{it.get('service','?')}] {it['title'][:55]}")

    if not args.no_merge:
        _merge_into_candidates(all_items)


if __name__ == "__main__":
    main()
