#!/usr/bin/env python3
"""
Jeeves Suggestion Engine — "Be Prepared" integration module.

Handles:
1. Reading suggestion_candidates.json from Elder Brain
2. Formatting suggestions for spoken delivery
3. Cadence management (not too frequent)
4. Context-aware offering (leisure mode vs. user-initiated)
5. Gentle profiling hooks (when to ask a taste question)

Usage:
    from suggestion_engine import SuggestionEngine
    engine = SuggestionEngine()

    # User asks: "Anything good on?"
    text, actions = engine.get_suggestions(user_initiated=True)

    # Contextual brief: leisure beacon triggered
    text, actions = engine.get_suggestions(user_initiated=False, context="living_room")
"""

import json
import random
import re
from datetime import datetime, timezone
from pathlib import Path

ELDER_BRAIN = Path.home() / "elder_brain"
CANDIDATES_PATH = ELDER_BRAIN / "suggestion_candidates.json"
PROFILE_PATH = ELDER_BRAIN / "taste_profile.json"
CADENCE_LOG = ELDER_BRAIN / "jeeves_cadence_log.json"
AFFINITY_PATH = ELDER_BRAIN / "viewing_affinity.json"   # legacy/household fallback

# Words that add no signal when matching watched titles to candidates
_NOISE_WORDS = {
    "the", "a", "an", "and", "of", "in", "on", "for", "to", "with", "at",
    "season", "episode", "official", "trailer", "best", "moments", "full",
    "hd", "4k", "1080p", "part", "part1", "part2", "scene", "clips", "clip",
    "video", "teaser", "preview", "finale", "recap", "s1", "s2", "s3", "s4",
}


def _title_overlap(watched: str, candidate: str) -> bool:
    """True if the watched title shares significant words with the candidate.
    Handles 'The Crown Official Trailer' vs 'The Crown: The Complete Series'.
    Matches on ≥2 shared words, or 1 shared word of ≥4 chars ('crown')."""
    w = {x for x in re.split(r"\W+", watched) if len(x) > 2 and x not in _NOISE_WORDS}
    c = {x for x in re.split(r"\W+", candidate) if len(x) > 2 and x not in _NOISE_WORDS}
    if not w or not c:
        return False
    shared = w & c
    if len(shared) >= 2:
        return True
    return bool(shared) and max(len(x) for x in shared) >= 4


class SuggestionEngine:
    """
    Manages when and how Jeeves offers suggestions.
    """

    def __init__(self, owner: str = "tom"):
        self.owner = owner
        self.candidates = self._load_candidates()
        self.profile = self._load_profile()
        self.cadence = self._load_cadence()
        self.affinity = self._load_affinity(owner)

    def _load_affinity(self, owner: str = "tom"):
        """Load viewing affinity for a specific owner (produced nightly by
        taste_learner.py). Falls back to the legacy household file, then {}."""
        owner_path = ELDER_BRAIN / f"viewing_affinity_{owner}.json"
        for p in (owner_path, AFFINITY_PATH):
            if p.exists():
                try:
                    with open(p) as fh:
                        return json.load(fh)
                except Exception:
                    pass
        return {}

    def _load_candidates(self):
        if CANDIDATES_PATH.exists():
            try:
                with open(CANDIDATES_PATH) as fh:
                    return json.load(fh)
            except Exception:
                pass
        return {"candidates": []}

    def _load_profile(self):
        if PROFILE_PATH.exists():
            try:
                with open(PROFILE_PATH) as fh:
                    return json.load(fh)
            except Exception:
                pass
        return {}

    def _load_cadence(self):
        if CADENCE_LOG.exists():
            try:
                with open(CADENCE_LOG) as fh:
                    return json.load(fh)
            except Exception:
                pass
        return {"last_suggestion_time": None, "count_today": 0, "last_date": ""}

    def _save_cadence(self):
        ELDER_BRAIN.mkdir(parents=True, exist_ok=True)
        with open(CADENCE_LOG, "w") as fh:
            json.dump(self.cadence, fh)

    def _reset_daily_count(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.cadence.get("last_date") != today:
            self.cadence["count_today"] = 0
            self.cadence["last_date"] = today

    def can_offer(self, context=None, user_initiated=False):
        """
        Check if suggestion is permitted by cadence rules.

        Returns: (can_offer: bool, reason: str)
        """
        if user_initiated:
            return True, "user_requested"

        # Check quiet hours (22:00 - 09:00)
        now = datetime.now(timezone.utc)
        hour = now.hour
        if hour >= 22 or hour < 9:
            return False, "quiet_hours"

        # Check frequency cap
        self._reset_daily_count()
        max_per_day = self.profile.get("cadence", {}).get("max_suggestions_per_day", 3)
        if self.cadence.get("count_today", 0) >= max_per_day:
            return False, "daily_cap_reached"

        # Check time since last suggestion
        last_time = self.cadence.get("last_suggestion_time")
        if last_time:
            try:
                last = datetime.fromisoformat(last_time)
                hours_since = (now - last).total_seconds() / 3600
                min_hours = self.profile.get("cadence", {}).get("min_hours_between_offers", 4)
                if hours_since < min_hours:
                    return False, "too_soon"
            except Exception:
                pass

        # Check active contexts
        active_contexts = self.profile.get("cadence", {}).get("active_contexts", ["living_room"])
        if context and context not in active_contexts:
            return False, "context_not_permitted"

        return True, "cadence_permits"

    def get_suggestions(self, user_initiated=False, context=None, count=3):
        """
        Return formatted suggestion text and action chips.

        Args:
            user_initiated: True if user asked; bypasses most gates
            context: str like "living_room", "car_passenger", etc.
            count: max suggestions to include

        Returns: (spoken_text: str, actions: list[dict])
        """
        can, reason = self.can_offer(context, user_initiated)
        if not can:
            return None, []  # Caller should not mention suggestions

        candidates = self.candidates.get("candidates", [])
        if not candidates:
            return None, []

        # Filter by owner: only show this owner's tagged candidates plus any
        # untagged/shared ones (fixed-channel scrapers have no owner tag).
        candidates = [
            c for c in candidates
            if not c.get("owner") or c.get("owner") == self.owner
        ]
        if not candidates:
            return None, []

        # Re-rank by viewing affinity (taste_learner output). Candidates
        # matching watched titles/artists/apps float to the top.
        candidates = self._rank_by_affinity(candidates)

        # Pick top N candidates
        picks = candidates[:count]
        if len(picks) < 1:
            return None, []

        # Build spoken text
        if user_initiated:
            # User asked — give full list
            spoken = self._format_user_requested(picks)
        else:
            # Proactive — brief, one suggestion only
            spoken = self._format_proactive(picks[0])
            picks = [picks[0]]

        # Build action chips
        actions = []
        for p in picks:
            url = p.get("url", "")
            if url:
                actions.append({
                    "type": "nav_deeplink",
                    "label": f"Open on {p.get('service', 'service').replace('_', ' ').title()}",
                    "url": url,
                    "provider": p.get("service", "unknown"),
                })

        # Record the offer
        self.cadence["last_suggestion_time"] = datetime.now(timezone.utc).isoformat()
        self.cadence["count_today"] = self.cadence.get("count_today", 0) + 1
        self._save_cadence()

        return spoken, actions

    def _rank_by_affinity(self, candidates: list) -> list:
        """
        Re-rank candidates using viewing_affinity.json. Boosts candidates
        whose title/artist/service appears in the household's actual viewing
        history. No affinity file or empty history → unchanged order.

        Boost: +0.15 for a title watch, +0.10 for artist, +0.05 for app.
        """
        affinity = self.affinity or {}
        title_aff = {k.lower(): v for k, v in (affinity.get("title_affinity") or {}).items()}
        artist_aff = {k.lower(): v for k, v in (affinity.get("artist_affinity") or {}).items()}
        app_aff = {k.lower(): v for k, v in (affinity.get("app_affinity") or {}).items()}
        if not (title_aff or artist_aff or app_aff):
            return candidates

        def score(c):
            boost = 0.0
            title = (c.get("title") or "").lower()
            artist = (c.get("artist") or "").lower()
            app = (c.get("service") or "").lower()
            for t, v in title_aff.items():
                if t and _title_overlap(t, title):
                    boost += 0.15 * min(v, 3)
            for a, v in artist_aff.items():
                if a and a in artist:
                    boost += 0.10 * min(v, 3)
            for a, v in app_aff.items():
                if a and a in app:
                    boost += 0.05 * min(v, 3)
            return c.get("score", 0.0) + boost

        # Stable sort: keep original order among equal scores
        indexed = [(score(c), i, c) for i, c in enumerate(candidates)]
        indexed.sort(key=lambda x: (-x[0], x[1]))
        return [c for _, _, c in indexed]

    def _format_user_requested(self, picks):
        """Format when user asks 'Anything good on?'"""
        if len(picks) == 1:
            p = picks[0]
            return (f"I've found one thing that might interest you, sir. "
                   f"{p['title']} by {p.get('artist', 'unknown')}. "
                   f"Would you like to have a look?")
        
        # Multiple picks
        intro = "I've found a few things that might interest you, sir. "
        items = []
        for p in picks:
            if p.get("type") == "music_album":
                items.append(f"{p['title']} by {p['artist']}")
            else:
                items.append(f"{p['title']}")
        
        items_text = ", ".join(items[:-1]) + f", and {items[-1]}" if len(items) > 1 else items[0]
        return intro + items_text + ". Shall I open one?"

    def _format_proactive(self, pick):
        """Format a brief proactive suggestion (one item)."""
        if pick.get("type") == "music_album":
            return (f"I noticed {pick['title']} by {pick['artist']} is trending, sir. "
                   f"Thought you might enjoy it. Shall I open it?")
        else:
            return (f"I noticed {pick['title']} is new this week, sir. "
                   f"Thought you might find it interesting.")

    def get_profile_question(self, interaction_count, context):
        """
        Check if it's time to ask a gentle profiling question.

        Returns: (question: str or None, domain: str)
        """
        # Import gentle profiler
        try:
            from gentle_profiler import GentleProfiler
            profiler = GentleProfiler()
            should, _ = profiler.should_ask(interaction_count, context, None)
            if should:
                q, domain = profiler.pick_question(context)
                return q, domain
        except Exception:
            pass
        return None, ""


def main():
    """Demo the suggestion engine."""
    engine = SuggestionEngine()

    # User-initiated request
    text, actions = engine.get_suggestions(user_initiated=True, count=3)
    if text:
        print("USER REQUESTED:")
        print(f"  Text: {text}")
        print(f"  Actions: {actions}")
    else:
        print("No suggestions available.")

    print("\n---")

    # Proactive (contextual)
    text2, actions2 = engine.get_suggestions(user_initiated=False, context="living_room", count=1)
    if text2:
        print("PROACTIVE (living room):")
        print(f"  Text: {text2}")
        print(f"  Actions: {actions2}")
    else:
        print("Proactive blocked by cadence.")


if __name__ == "__main__":
    main()
