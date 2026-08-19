# Suggestion Pipeline Design Doc
## GeezerAid — "Be Prepared, Not Naggy"

### Principle
Jeeves never pushes recommendations. He **maintains a prepared list** of suggestion
candidates (new releases, upcoming films) cross-referenced with the elder's taste
profile. The list is offered **only when the user asks or the context explicitly
invites it** (leisure mode, living room, no pending appointments).

### Architecture

```
Public feeds (Apple Music API, Netflix/Whats-on-Netflix scraper)
    → Weekly cron on Strix
    → Taste-filter (cross-reference with taste_profile.json)
    → Store suggestion_candidates.json in Elder Brain
    → Jeeves reads at suggestion-intent time
```

### taste_profile.json schema

```json
{
  "version": 1,
  "elder_name": "Tom",
  "last_updated": "2026-07-28",
  "music": {
    "genres": ["prog-rock", "jazz", "classical"],
    "artists": ["Pink Floyd", "Charles Mingus", "Kamasi Washington"],
    "eras": ["1970s", "2020s"],
    "avoid": ["country", "EDM"]
  },
  "film": {
    "directors": ["Hayao Miyazaki", "Stanley Kubrick", "Christopher Nolan"],
    "genres": ["sci-fi", "animation", "thriller"],
    "eras": ["1980s", "1990s", "2010s"],
    "avoid": ["horror", "reality TV"],
    "rewatch_favorites": ["Blade Runner", "Spirited Away"]
  },
  "conversation_extracted": {
    "likes": ["mentioned enjoying 'Dark' on Netflix", "said he loves Miles Davis"],
    "dislikes": ["dismissed superhero films", "said he hates reality TV"],
    "friends_mentioned": {
      "Bob": {"interests": ["golf", "history documentaries"], "last_mentioned": "2026-07-20"}
    }
  },
  "cadence": {
    "max_suggestions_per_day": 3,
    "min_hours_between_offers": 4,
    "active_contexts": ["living_room", "car_passenger"],
    "quiet_hours_start": "22:00",
    "quiet_hours_end": "09:00"
  },
  "sources": {
    "apple_music_enabled": true,
    "netflix_enabled": true,
    "youtube_music_enabled": false
  }
}
```

### suggestion_candidates.json schema (output)

```json
{
  "generated_at": "2026-07-28T08:00:00Z",
  "source": "apple_music",
  "candidates": [
    {
      "type": "music_album",
      "title": "The Endless River",
      "artist": "Pink Floyd",
      "genre": "prog-rock",
      "url": "https://music.apple.com/...",
      "match_score": 0.95,
      "match_reason": "favorite_artist + matching_genre"
    }
  ]
}
```

### Cadence Rules (hard constraints)

1. **Context-gated:** Only offer in `active_contexts` (leisure spaces, not bedroom/bathroom).
2. **Frequency cap:** Max `max_suggestions_per_day` per 24h window.
3. **Quiet hours:** No proactive suggestions between `quiet_hours_start` and `quiet_hours_end`.
4. **Rejection learning:** If user dismisses (`"no thanks"`, `"not interested"`), record the genre/director/time combo and weight it down for 7 days.
5. **User-initiated bypass:** When user asks *"anything good on?"* or *"what's new this week?"* — all gates bypassed, Jeeves reads the full prepared list.

### Integration Points

- **Chat intent:** `"suggestion_request"` — user asks for recommendations.
- **Contextual brief:** `"leisure"` context — beacon in living room, evening, no calendar events.
- **Nav action:** Suggestions rendered as chips: *"Listen to new Pink Floyd"* → deep link to Apple Music.

### Data Sources

| Source | Method | Status | Auth |
|---|---|---|---|
| Apple Music | Official API (`api.music.apple.com/v1/catalog/{storefront}/new-releases`) | Ready | JWT Developer Token |
| Netflix | Scrape `whats-on-netflix.com` + Netflix Tudum | Ready | None |
| YouTube Music | `ytmusicapi` unofficial | Optional | Cookie auth |

### Cron Schedule

- **Apple Music:** Weekly, Mondays 06:00
- **Netflix:** Weekly, Mondays 06:30
- **Taste profile update:** Daily, from conversation logs

### Files

- `~/elder_brain/taste_profile.json` — canonical taste profile
- `~/elder_brain/suggestion_candidates.json` — prepared suggestions
- `~/Public/GA-V9/tools/apple_music_scraper.py` — scraper script
- `~/Public/GA-V9/tools/netflix_scraper.py` — scraper script
