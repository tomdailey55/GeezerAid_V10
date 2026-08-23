#!/usr/bin/env python3
"""
Jeeves Gentle Profiling System — "Getting to know you, one question at a time."

Design principle: Jeeves learns the elder's preferences gradually, embedded in
natural conversation. Never surveys. Never "grills." A single question per
interaction, asked only when context permits.

Uses the Elder Brain as the knowledge store; taste_profile.json is the
accumulated result.
"""

import json
import random
import re
from datetime import datetime, timezone
from pathlib import Path

ELDER_BRAIN = Path.home() / "elder_brain"
PROFILE_PATH = ELDER_BRAIN / "taste_profile.json"
CONVERSATION_LOG = ELDER_BRAIN / "jeeves_conversation_log.jsonl"
PROFILE_SNIPPETS = ELDER_BRAIN / "jeeves_profile_snippets.json"

# ── Question pools: one per domain, asked contextually ──

MUSIC_QUESTIONS = [
    "If you were putting something on while reading the paper, what would it be?",
    "Who's an artist you always come back to, even after years?",
    "Is there a genre you used to love but don't listen to much anymore?",
    "Who's someone you discovered recently that surprised you?",
    "What's the last album you played all the way through?",
    "Is there music that reminds you of a particular time in your life?",
]

FILM_QUESTIONS = [
    "What kind of film do you reach for when you want to relax?",
    "Is there a director whose films you always watch?",
    "What was the last film you really enjoyed?",
    "Are there films you'd happily watch again and again?",
    "What kind of film would you never choose to watch?",
    "Is there an actor or actress you always enjoy?",
]

TV_QUESTIONS = [
    "What's a show you've watched more than once?",
    "Is there a series you're looking forward to returning?",
    "What kind of programme do you put on in the background?",
    "Is there a show everyone recommended but you couldn't get into?",
]

FRIEND_QUESTIONS = [
    "How is {name}? What are they up to these days?",
    "When did you last see {name}?",
    "Does {name} still {activity}?",
]

MEMORY_QUESTIONS = [
    "Where did you grow up, if I may ask?",
    "What did you do before you retired?",
    "Is there a place you always meant to visit but never did?",
]


class GentleProfiler:
    """
    Manages when and what Jeeves asks to learn preferences.
    """

    # Ask at most one question every N interactions (not every chat)
    MIN_INTERACTIONS_BETWEEN_QUESTIONS = 5
    # Skip if the conversation is about something urgent/functional
    SKIP_CONTEXTS = ["emergency", "medication", "appointment", "navigation"]

    def __init__(self):
        self.profile = self._load_profile()
        self.snippets = self._load_snippets()

    def _load_profile(self):
        if PROFILE_PATH.exists():
            with open(PROFILE_PATH) as fh:
                return json.load(fh)
        return {}

    def _load_snippets(self):
        """Load already-asked questions + answers to avoid repetition."""
        if PROFILE_SNIPPETS.exists():
            with open(PROFILE_SNIPPETS) as fh:
                return json.load(fh)
        return {"asked": [], "answers": []}

    def should_ask(self, interaction_count, current_context, last_question_time):
        """
        Decide whether this interaction is a good moment for a profile question.

        Args:
            interaction_count: total number of Jeeves interactions today
            current_context: str, e.g. "car", "living_room", "kitchen"
            last_question_time: datetime or None

        Returns: (should_ask: bool, reason: str)
        """
        # Don't ask too frequently
        if interaction_count < self.MIN_INTERACTIONS_BETWEEN_QUESTIONS:
            return False, "too_soon"

        # Don't ask in functional contexts
        if current_context in self.SKIP_CONTEXTS:
            return False, "functional_context"

        # Don't ask if we asked recently (time-based, not count-based)
        if last_question_time:
            hours_since = (datetime.now(timezone.utc) - last_question_time).total_seconds() / 3600
            if hours_since < 2:
                return False, "asked_recently"

        # Don't ask if we've already covered this domain recently
        recent_domains = self._recent_question_domains(lookback=10)
        if len(recent_domains) >= 3:
            return False, "covered_all_domains"

        return True, "context_permits"

    def _recent_question_domains(self, lookback=10):
        """Which domains have we asked about in the last N interactions?"""
        asked = self.snippets.get("asked", [])
        recent = asked[-lookback:] if len(asked) > lookback else asked
        domains = set()
        for q in recent:
            for domain in ["music", "film", "tv", "friend", "memory"]:
                if domain in q.get("type", ""):
                    domains.add(domain)
        return domains

    def pick_question(self, current_context, elder_name="Tom"):
        """
        Select a question based on what's unknown in the profile.
        Prefers domains with the least data.
        """
        # Score domains by "information gap"
        gaps = self._information_gaps()

        # Pick the domain with the biggest gap
        domain = max(gaps, key=gaps.get)

        # Pick a question from that domain not recently asked
        questions = self._questions_for_domain(domain, elder_name)
        asked_texts = {a.get("question", "") for a in self.snippets.get("asked", [])}
        available = [q for q in questions if q not in asked_texts]

        if not available:
            # All questions in this domain asked — mark as complete
            return None, domain

        question = random.choice(available)
        return question, domain

    def _information_gaps(self):
        """Return a score for each domain: higher = more we don't know."""
        gaps = {}
        profile = self.profile

        # Music gap
        music = profile.get("music", {})
        gaps["music"] = 5 - len(music.get("artists", [])) * 0.5 - len(music.get("genres", [])) * 0.3
        gaps["music"] = max(0, gaps["music"])

        # Film gap
        film = profile.get("film", {})
        gaps["film"] = 5 - len(film.get("directors", [])) * 0.5 - len(film.get("genres", [])) * 0.3
        gaps["film"] = max(0, gaps["film"])

        # TV gap
        tv = profile.get("tv", {})
        gaps["tv"] = 5 - len(tv.get("shows", [])) * 0.5 - len(tv.get("genres", [])) * 0.3
        gaps["tv"] = max(0, gaps["tv"])

        # Friend gap
        friends = profile.get("conversation_extracted", {}).get("friends_mentioned", {})
        gaps["friend"] = 3 - len(friends) * 0.5
        gaps["friend"] = max(0, gaps["friend"])

        # Memory gap
        memory = profile.get("memory", {})
        gaps["memory"] = 3 - (1 if memory.get("hometown") else 0) - (1 if memory.get("career") else 0)
        gaps["memory"] = max(0, gaps["memory"])

        return gaps

    def _questions_for_domain(self, domain, elder_name):
        """Return question list for domain, with personalization."""
        if domain == "music":
            return MUSIC_QUESTIONS
        elif domain == "film":
            return FILM_QUESTIONS
        elif domain == "tv":
            return TV_QUESTIONS
        elif domain == "friend":
            # Personalize with known friend names
            friends = self.profile.get("conversation_extracted", {}).get("friends_mentioned", {})
            if friends:
                name = random.choice(list(friends.keys()))
                activity = friends[name].get("interests", ["doing well"])
                return [q.format(name=name, activity=activity[0]) for q in FRIEND_QUESTIONS]
            return []
        elif domain == "memory":
            return MEMORY_QUESTIONS
        return []

    def record_answer(self, question, domain, user_response):
        """Store the question+answer and attempt to extract taste signals."""
        self.snippets.setdefault("asked", []).append({
            "question": question,
            "domain": domain,
            "asked_at": datetime.now(timezone.utc).isoformat(),
        })
        self.snippets.setdefault("answers", []).append({
            "question": question,
            "answer": user_response,
            "extracted_signals": self._extract_signals(domain, user_response),
            "answered_at": datetime.now(timezone.utc).isoformat(),
        })
        self._save_snippets()

    def _extract_signals(self, domain, text):
        """Naive extraction of taste signals from free-text response."""
        signals = []
        text_lower = text.lower()

        if domain == "music":
            # Look for "I like X", "I love X", "X is my favorite"
            for match in re.finditer(r'(?:like|love|enjoy|favorite)\s+([\w\s\-\'"]+)', text_lower):
                signals.append({"type": "artist_or_genre", "value": match.group(1).strip()})

        elif domain in ("film", "tv"):
            for match in re.finditer(r'(?:like|love|enjoy|watch|director)\s+([\w\s\-\'"]+)', text_lower):
                signals.append({"type": "title_or_genre", "value": match.group(1).strip()})

        return signals

    def _save_snippets(self):
        ELDER_BRAIN.mkdir(parents=True, exist_ok=True)
        with open(PROFILE_SNIPPETS, "w") as fh:
            json.dump(self.snippets, fh, indent=2)


def main():
    """Demo the profiler."""
    profiler = GentleProfiler()

    should, reason = profiler.should_ask(
        interaction_count=6,
        current_context="living_room",
        last_question_time=None
    )
    print(f"Should ask? {should} ({reason})")

    if should:
        q, domain = profiler.pick_question("living_room", "Tom")
        print(f"\nDomain: {domain}")
        print(f"Question: {q}")

        # Simulate answer
        profiler.record_answer(q, domain, "I really enjoy Pink Floyd and jazz like Miles Davis")
        print(f"\nExtracted signals: {profiler._extract_signals(domain, 'I really enjoy Pink Floyd and jazz like Miles Davis')}")


if __name__ == "__main__":
    main()
