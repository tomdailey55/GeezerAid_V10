# GA iOS App — Scope (2026-08-14)

**Purpose:** Scope the GA iOS client. Grounded in what actually exists today, and the
decisions made on Siri-AI capability, device targets, and the watch-as-input.

**Owner:** Tom · **Server:** MBP `100.85.123.9:8766` (BaseHTTPRequestHandler)

---

## 1. Current reality (verified — do not rebuild)

- **Client:** Flutter (`ga_flutter/`), talks to the MBP server over HTTP.
- **Endpoints used:** `/chat` (voice loop), `/stt`, `/photo` (camera → local VLM),
  `/contextual_brief`. Plus in-app: beacon/location discovery, recommendations screen,
  user prefs, Google integration.
- **No `/ws` WebSocket on the server** (the watch fall-event bridge assumed it — gap, park it).

## 2. Core principles

- **One app, not two.** GA is server-driven and device-agnostic. The iPhone 13 and an
  iPad Pro run the identical GA client. "Smarts" live on the MBP, not the client.
- **The voice loop is the heart and it stays.** Push-to-talk → `/chat` → Jeeves → reply.
  Works on every device. Don't rebuild it.
- **Progressive enhancement, not a split.** Siri-AI capability only *adds* an optional
  reach-in layer on capable devices; it never changes core behavior.

## 3. Siri entry — two layers, only one gated

| | Classic Siri + App Intents | Siri AI |
|---|---|---|
| Hardware gate | **None** (works on iPhone 13 / A15) | A17 Pro+ / M1+ only |
| "Hey Siri, talk to Jeeves" | ✅ **every device** | ✅ (richer) |

The basic voice entry to GA is **universal**. Only the richer content/action reach-in
needs Siri-AI hardware.

## 4. Scope (phased)

### Phase A — Voice entry everywhere (foundation, largely done)
- Push-to-talk → Jeeves (works today).
- **App Intent: "Talk to Jeeves"** (NEW) — "Hey Siri, talk to Jeeves" starts a voice
  session on any device. Small, high-value, works on every hardware.

### Phase B — Self-control actions (NEW, the active thread) — PRIMARY TARGET
- The app drives **its own phone**: server returns an action alongside the reply
  (e.g. `intent: ipad`, `tier: server`), the app executes it natively via the WDA path.
- Examples: "Jeeves, open the Weather app" → opens Weather on this phone.
  "Jeeves, open Settings / navigate / type" → same.
- Uses the now-reliable WDA `open` (visible-icon class chain) built this session.
- **Self-control is the primary target** — the phone controlling the iPad is secondary.

### Phase C — Siri-AI reach-in (capable devices only, optional)
- Expose GA actions + Elder Brain content as App Intents.
- Registers only on A17 Pro+/M1+; **no behavior change on iPhone 13**.

### Watch as push-to-talk substitute (NEW, confirmed helpful)
- A tap on the Apple Watch → paired iPhone GA app **starts listening** (one-way
  "start listening" relay from watch to phone).
- Simpler than the fall-event `/ws` bridge (no server WebSocket needed for this).
- Watch on the wrist = the mic button is always in reach.

## 5. Explicitly out of scope
- **Two apps** — no. One app, capability-gated reach-in.
- **Rebuilding the voice loop** — it works; don't touch it.
- **Fall-detection event forwarding** — tabled (no Apple entitlement work).
- **The watch `/ws` fall bridge** — no server endpoint; parked.

## 6. Decision log
- **Self-control first** (app drives its own phone) — more frequent than phone-as-iPad-remote.
- **Watch substitutes for push-to-talk** — confirmed helpful; simpler than the fall bridge.
- **One universal app** — Siri-AI adds an optional layer, never a second app.

## 7. Watch items
- Confirm the "Talk to Jeeves" App Intent compiles on watchOS (for the watch tap → phone
  listen relay).
- Whether the watch → phone "start listening" relay uses WatchConnectivity or a shared
  App Intent.
- Server: no change needed for Phase B self-control (reuse `/chat` action routing).
