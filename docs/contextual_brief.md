# Contextual Brief — proactive Jeeves (beacon-triggered)

Proactive agent brief fired when a named beacon context is entered (e.g. `car`).
The beacon is only a *trigger*; the brief is synthesized server-side by running
tool-call-shaped data through the local LLM. Phase-0 uses seeded stub tools
(editable JSON, no API keys). Later phases swap stubs for live Google/HERE calls
with the **same schema**, so the prompt and orchestration don't change.

## Endpoint (Mac server, ~/Public/GA-V9/server_v9.py)

```
POST /contextual_brief
{ "context": "car", "user_id": "andrea",
  "device_location": {"lat": 41.6, "lng": -87.0},   // nullable (WiFi iPad has none)
  "discreet": false }                                // suppress names/street #s aloud
->
{ "text": "...Jeeves brief...",                       // TTS-ready
  "audio": "base64 wav | null",                      // Kokoro; null if TTS down
  "actions": [ {"type":"nav_deeplink","url":"...","label":"Navigate","provider":"google"} ],
  "context": "car",
  "tools_called": ["calendar_today","location","todos_pending","directions","send_to_nav"],
  "latency_ms": 2968.4 }
```

The Flutter client plays `text`/`audio` via the existing TTS path and renders any
`actions` as tappable chips (Google Maps / Waze deep link).

## Tool schema (OpenAI function format — what Ollama :8080 would consume)

```
calendar_today    -> {}                       today's events: title, start, end, location, notes
location          -> {}                       device GPS if present, else configured HOME
todos_pending     -> {}                       incomplete items, each optional location + near_route_home
directions        -> {origin, destination, depart_now=true}
                                            ETA, distance, and whether fastest != direct (=> delay on primary)
send_to_nav       -> {destination, provider:"google"|"waze"="google"}
                                            returns a deep link; NEVER a free-text route
traffic_incidents -> {bbox}                 OPTIONAL (HERE/TomTom); only source of a literal
                                            "wreck on 49" — see limitation
```

## System prompt (Jeeves, context-aware)

- Acknowledge the context ("I see you're in your car").
- Infer the destination from `calendar_today`; state it as a *confirm-able
  assumption*, not a question ("I assume you're headed to Dr. Patel").
- Call `directions`; if fastest != direct, recommend the alternate + give ETA.
  ONLY name a specific incident if `traffic_incidents` returned it; else
  "there's a delay on 49".
- From `todos_pending`, name items where `near_route_home` is true.
- End with EXACTLY ONE question, then stop. Never dump the full list unprompted.
- `discreet=true`: "your appointment" not the doctor's name, no street numbers.

## Orchestration (server-side)

Prefetch the independent facts (calendar_today, todos_pending, location) BEFORE
the model loop to cut a round-trip. The LLM then calls directions (depends on
inferred destination) and send_to_nav. If the loop/model fails, a template
fallback still produces a coherent brief (implemented in _handle_contextual_brief).

## Honest limitations

- "Wreck on 49" is NOT free: Google Directions gives ETA + alt-route hint, not
  incident causes. `traffic_incidents` (HERE/TomTom, paid) is required for the
  literal phrasing; otherwise say "delay on 49".
- WiFi-only iPad = no GPS -> device_location null -> Strix assumes HOME origin.
  The iPhone (eventually) or cellular iPad fixes this.
- Latency: 122B Q4 ~5-15s/gen; tool loop 2-3 gens -> 15-45s. Fine for a pre-drive
  brief, not real-time nav. Phase-0 Mac 9B answered in ~3s.
- Privacy: location + calendar + driving patterns are sensitive. Local-first;
  `discreet` flag avoids voicing addresses in public; Jeeves should ask before
  reading anything private aloud.

## Phase-0 stubs (no API keys) — ~/Public/GA-V9/ga_context.json

Editable JSON: user, home, calendar_today[], todos_pending[], directions{},
nav{google_maps_url, waze_url}. Each stub tool returns from this file; swap for
live Google/HERE calls later (same output shape).

## Integration status

- [x] Mac server: /contextual_brief + 5 stub tools + template fallback (validated via curl, 200, ~3s)
- [x] ga_context.json editable config
- [x] LLM path works (Mac 9B answered; template fallback if model down)
- [x] Flutter: `car` beacon context -> /contextual_brief (play text/audio + nav chip)
- [ ] Live Google Calendar OAuth + Directions + (optional) HERE incidents
- [ ] GPS source decision (iPhone / cellular iPad)
