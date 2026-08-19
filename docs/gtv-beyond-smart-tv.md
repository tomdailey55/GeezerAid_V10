# Genius TV — Capabilities Beyond a Smart TV

**Status:** Idea capture (2026-08-18) — brainstorm, not yet designed
**Companion to:** `gtv-architecture.md`

## The core realization

A smart TV is a **kiosk**: fixed OS, app grid, one video surface, a remote that
sends D-pad events. The manufacturer decides what's possible.

The Genius TV is a **general-purpose Linux computer** with an agent, a
microphone, room awareness, a knowledge vault, and four TVs it can drive via
ADB. The video isn't the application — it's *one element in a composition
Jeeves controls*.

That single difference — **video as an element, not the app** — is the source of
every capability below.

> **A smart TV is a window you look through. Jeeves makes the screen a surface
> the house thinks on.**

---

## 1. The second screen is inside the same screen

Video occupies a tile; the rest of the surface is live context. Jeeves knows
what's playing, so the context tile is about *this scene*, not generic.

- "Who is that?" → actor tile fills in, video keeps playing
- "What else was she in?" → filmography beside the show
- Cooking: vault ingredient list left, video right — *"back up to the flambé
  step"* jumps the video while instruction step 5 highlights

Genuine capability no TV has: **your notes and the source video, cross-linked,
both live.**

## 2. Video that answers questions about itself

Strix has a VLM (`:8086`, already used for TV screen reading) — Jeeves can
*look at the frame*.

- "What's that building?" — no metadata needed, VLM reads the screen
- "What does that sign say?" — on-screen text translation
- "Rewind to where they're in the kitchen" — scene-based navigation, not
  timestamps

A smart TV cannot do this: no model, no eyes on its own output, no notion of
scene content.

## 3. Gesture control — the honest version

Full gesture *navigation* is a trap (Kinect/Leap lesson): tiring, imprecise,
worse than a remote. **Where gesture wins is hands you can't use.**

- Cooking, hands covered in flour → open palm = pause, wave = next step
- **Volume as a dial** — raise/lower hand; the one continuous control that
  genuinely feels better as a gesture
- **"Shush" gesture** (finger to lips) → instant mute; faster than a phrase,
  complements "Quiet, Jeeves"

**Design rule:** gestures for coarse, urgent, hands-busy actions. Voice for
specificity. Remote for precision navigation.

**Cheaper first step:** presence/proximity rather than gesture — camera or the
existing BLE beacons detect entry/exit. Pause on exit, resume on return, no
hand movement at all.

## 4. Room-aware and person-aware playback

Wake-word-as-identity pays off here: Jeeves knows **who** and **where**.

- **Follow-me video** — pause in the kitchen, "continue in the bedroom,"
  resumes at the exact timestamp on that room's screen
- **Per-person resume points** — Andrea's position is hers, yours is yours;
  same account, same TV, different people, no profile switching
- Andrea walks in during your show → Jeeves knows both are present and adjusts
  what it volunteers (affinity ranking stays silent, per house rule)

## 5. Multi-source composition

A smart TV shows one app at a time. Jeeves composes *across services*.

- "Show me the game and the fantasy scores" — different providers, one surface
- "Reviews of this while it plays" — the Game of Thrones case
- **Four TVs as one canvas** — same event on multiple screens, or four camera
  angles across rooms

## 6. Video as an *answer format*, not a destination

Possibly the most important reframe. Video becomes one way an answer arrives.

- "How do I bleed a radiator?" → plays the relevant 40 seconds, steps as text
  beside it
- "What did we decide about the deck?" → vault note + photo + contractor's
  video walkthrough
- Skips intros, sponsors, padding — **Jeeves plays the useful segment**,
  because it read the transcript

Video subordinated to intent. No TV does this because no TV knows what you're
trying to accomplish.

## 7. Sovereignty

- No recommendation engine with its own agenda — your affinity rules, silent
- Nothing leaves the house without permission (viewing logger already honors)
- No forced UI redesign — yours changes when *you* decide
- Support to 2033+ — it's a Linux box; outlives any TV's firmware

---

## 8. Video as a time machine — rolling buffer

- "What did she just say?" → replay last 15s *with captions* on the context
  tile, show continues
- "Clip that" → last 30s to the vault with auto-context (*"S1E1, 47:12, the
  Ned Stark line"*)
- Ambient TV as a searchable log — not surveillance of *you*, but of what was
  on: "what was that documentary I half-watched Tuesday?"

**Reframe:** live TV becomes retroactively addressable.

## 9. Jeeves as editor, not just player

Transcripts + VLM + four screens = a small editing suite.

- "Just the recipe parts" → 12-minute vlog cut to the 3 minutes of cooking,
  cuts computed from transcript
- "Watch this with me later" → boring bits pre-marked
- **Auto-supercut** — "every scene with Tyrion," from subtitle timings
- "Give me the 5-minute version" of a 3-hour game

**Reframe:** synthesize a new cut on demand — categorically beyond playback.

## 10. The household's shared attention layer

- "Andrea, come see this" → clip appears on the screen nearest her with a
  gentle chime — not a shout across the house
- **Deferred sharing** — "save this for Andrea" → surfaces on her next TV
  session, unprompted, once
- **Watch-together across rooms** — same timestamp, two rooms, synced
- **"What did I miss" handoff** — walk in mid-show, get a one-sentence
  catch-up on the context tile instead of rewinding

**Reframe:** TV as a communication medium inside the house.

## 11. Video reaching into the physical house

With Home Assistant + four TVs + rooms:

- **Cinematic lighting** — dim as the film starts; lightning scene flickers
  the room
- **Doorbell interrupt** — video auto-pauses, camera feed takes the context
  tile, resumes when they leave
- **Cooking mode as a house state** — recipe on screen, timers set, kitchen
  lights up, music down, calls held
- **"Movie night"** in one utterance → TV on, lights down, phones DND,
  popcorn timer, doorbell to silent-notify

**Reframe:** video is a household *mode*, not a screen state.

## 12. The anti-recommendation engine

Jeeves has no incentive to push content — which permits something novel.

- **Cross-service honest search** — "where can I watch X, cheapest"; no
  service will say it's free elsewhere
- **"Is this worth my time?"** — reads reviews, checks the vault for whether
  you bailed on similar, answers *"probably not, sir"*
- **Finite-evening filter** — "90 minutes and I'm tired" → three options that
  actually fit, not infinite scroll
- **Anti-cliffhanger** — "does this end properly, or was it cancelled?"
- **Cost governance** — "we haven't used HBO in 5 weeks, sir. Cancel it?"

**Reframe:** an advocate on your side of the screen. Possibly the highest
*value* item here — saves money and time rather than adding features.

## 13. Accessibility first-class — the GeezerAid heart

Closest to the project's actual purpose.

- **"Slow that down and make it louder"** — speed + dialogue-boost on voice
- **Dialogue isolation** — "I can't hear the words" is the most common
  complaint about modern TV, is a solvable audio-processing problem, and *no
  TV solves it well*
- **Auto-captions on anything** — including services with poor caption
  support, generated locally by whisper.cpp
- **"Who's that again?"** — running cast tile for anyone losing track
- **Plain-language plot summary** on demand mid-episode, no spoilers past the
  current timestamp

For an elder-focused product, **"make TV comprehensible again"** may be a
stronger pitch than any clever composition feature.

## 14. The show becomes a hyperlink

- "That's a nice chair" → VLM identifies it, context tile shows what it is
- "Where is that filmed?" → map tile, *"40 minutes from your sister's place"*
- "Add that dish to my recipes" → Jeeves finds it and writes to the vault
- "That song?" → identified, saved to a playlist

**Reframe:** everything on screen is queryable; video stops being a sealed
rectangle.

## 15. Programming with intent, not channels

- "Something like the last thing we enjoyed, but shorter"
- "Play something Andrea would like too" — the intersection, computed silently
- **"Background noise, nothing I need to follow"** — a category no service
  offers
- Standing order: *"if there's a new episode of X, tell me at dinner"* — this
  is a **cron job**, which Jeeves already has
- "Wake me if the game gets close" — conditional attention on live content

**Reframe:** the TV takes instructions about the future, not just commands
about now.

## 16. The screensaver earns its keep

The art loop is currently decorative; it could be the ambient information
layer. **The idle state is the most-seen state.**

- Art that shifts palette by time of day and weather
- A painting that quietly *becomes* the thing you need — recipe fades in as
  you enter the kitchen at 6pm
- Rotating household memory — photos from this week last year, from the vault
- Presence-gated: on entry, one useful line — *"trash day tomorrow, sir"*

---

## Where the bets are (honest triage)

**Highest value, lowest effort — build first:**
1. Context tile beside video (#1) — dashboard already does this
2. Dialogue clarity + slow-down (#13) — closest to GeezerAid's purpose
3. Presence-based pause/resume (#3, #11) — beacons already exist
4. Subscription cost governance (#12) — saves actual money

**Highest ceiling, worth real effort:**
5. Video as answer format / transcript-driven playback (#6, #9)
6. "What did I miss" catch-up (#10)
7. Rolling buffer + "what did she say?" (#8)

**Fun but disciplined:**
8. Two or three coarse gestures only (#3) — hands-busy cooking
9. Living screensaver (#16) — cheap polish on the most-seen screen

**Honest cautions:**
- Auto-supercuts (#9) get compute-expensive — lovely demo, questionable daily
  use
- Rolling buffer (#8) raises privacy questions to decide deliberately, given
  Andrea's opt-in
- Anything camera-based needs an explicit household conversation first
