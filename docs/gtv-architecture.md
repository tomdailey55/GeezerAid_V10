# GTV Architecture — Mini-PC-per-Screen Household

**Status:** Decision record (2026-08-17)
**Owner:** Tom / Jeeves
**Supersedes:** the single-Strix Genius TV as the only screen
**See also:** `gtv-beyond-smart-tv.md` — 16 capabilities a smart TV structurally
cannot offer (idea capture, awaiting detailed design)

## Vision

Every room gets a screen where it makes sense:
- **Big screens** (43"–65") where they earn their place — living room, theater, kitchen wall
- **Smaller screens** (wall- or stand-mounted) elsewhere — bedrooms, office, hallway
- Each screen is driven by an **attached mini-PC (Linux)**
- All mini-PCs talk to the **household server — Strix** (the brain, model host, orchestrator)
- **Phones, iPads, Android tablets** are scattered control surfaces (web/PWA remote)

This is the "smart speakers with a screen" vision made concrete, and it's the
pattern already proven on Strix (mini-PC → 43" Genius TV).

## The edge device — ~$250 mini-PC (NOT Pi, NOT Mac mini)

**Target spec (researched 2026-08-17):**
- **Intel N150** (Twin Lake) — the current sweet spot
- **16 GB DDR4** (upgradeable to 32 GB)
- **M.2 NVMe** storage
- **~7–9 W idle** (headless) — minimal power, silent, always-on
- **~$180–250**

**Concrete candidates:**
| Model | CPU | RAM | Price | Notes |
|---|---|---|---|---|
| **GMKtec G3 Plus** | N150 | up to 32 GB | ~$250 | 2.5GbE, best overall |
| **Beelink Mini S13** | N150 | 16 GB | ~$200 | newer budget model |
| **Beelink S12 Pro** | N100 | 16 GB | ~$150 | cheapest, proven |
| **Minisforum UN100C** | N100 | 16 GB | ~$200–230 | fanless |

**Why N150/N100, not Pi:** x86, more RAM headroom, cheaper than a 16 GB Pi 5,
and the N100/N150 class is the proven Home Assistant / always-on workhorse.
**Why not Mac mini:** far more than needed for a thin client; the ~$250 class
is the right cost/performance for a per-room screen driver.

## Thin client with local fallback (the key design decision)

Each mini-PC is a **thin client by default** — it drives the screen and streams
voice to Strix. But it carries a **minimal local fallback** so the room isn't
dead if Strix drops:

- **Local wake-word** on the mini-PC (always listening, no Strix needed)
- **Tiny local model** (e.g. Qwen2.5-0.5B) for basic queries when Strix is down
- **Heavy lifting** (chat, reasoning, TTS, orchestration) → Strix when it's up

**The guardrail:** do NOT let each mini-PC become a mini-Strix. The value is
centralization — one brain, many thin screens. The local fallback is *just
enough* to keep the room alive, not a full replica.

## Control surfaces — device-agnostic by design

The web/PWA remote (served by Strix, `gtv_remote.html`) is the universal
control surface. It works on **any** device with a browser:
- Phone (iOS or Android)
- iPad on the table
- Android tablet
- Even the TV itself

No app per platform, no lock-in. "Grab whatever's handy" is solved by the web
page, not by a native app.

**Deeper agentic control** (Jeeves reaching *into* a device) is easier on
**Android** (ADB, open) than iOS (APNs wall) — aligns with the open-hardware
direction. But the basic control surface needs no platform at all.

## Wake word = user identity (design principle)

Each user's wake word is their **identity signal** — no login, no "who's
speaking" ambiguity. Saying your name selects your profile.

- **Tom** → "Jeeves" (default)
- **Andrea** → a different name + a different TTS voice

**Why it's good:**
- Per-user tailoring (viewing/recs, preferences) becomes automatic — the wake
  word selects the profile
- Per-user voice — the household doesn't all sound like Tom's Jeeves
- Natural — no new ritual, you just say your own name

**Design rules:**
- **Multi-class wake word** — extend the match set from one name to N names
  (whisper.cpp already transcribes; match against a set, not a single phrase)
- **"Current user" state** — the last wake word sets the current user; it can
  switch mid-conversation ("Andrea, what's the weather?" after Tom woke it)
- **Voice follows user** — Kokoro supports multiple voices; the TTS voice
  follows the current user
- **Mute phrases stay per-user** — "Mute Jeeves" / "Quiet, Jeeves" (Tom);
  Andrea's equivalent uses her name

## Android = household telephony & voice surface (design note)

The open-hardware direction favors an **Android phone** as the household's
primary telephony/voice surface — the device Jeeves can reach into most deeply,
because Android exposes open telephony, notification, and ADB APIs that iOS
keeps locked down.

**The call-routing model (forwarding, not Apple continuity):**
- Keep the iPhone number canonical; forward it carrier-level to the Android
  (Settings → Phone → Call Forwarding). Basic forwarding works flawlessly
  cross-OS; Apple-style simultaneous-ring/handoff does NOT exist across the
  fence.
- The Android becomes the "voice handler" — every call to the iPhone number
  lands on the device Jeeves can actually supervise.

**What Jeeves can do on the Android (real, open APIs):**
- **Call screening** (Call Screening API, Android 10+) — announce/decline/
  route spam and expected callers automatically
- **Call-state detection** (PHONE_STATE broadcast) — Genius TV shows "incoming
  call from Andrea," Jeeves pauses ambient audio during calls
- **Notification access** (NotificationListenerService) — announce/act on
  message notifications across the household screens
- **ADB control** (already in use) — full device reach: launch apps, intents

**Honest limits:**
- Call Screening API is gated with constrained response options
- Notification access requires a user-granted permission at setup
- Call audio interception (recording/rerouting) is not cleanly doable

**Candidate device:** Fairphone 6+ (7s Gen 4, 12GB LPDDR5, Android 16 to 2033,
unlocked bootloader, iFixit 10/10, /e/OS-degoogled option, ~$649) — a credible
edge/control node + repairable/open telephony surface. A Linux *phone* is the
purest but least practical for GA (no GA client in phone form, immature drivers);
Android (+ /e/OS for degoogled) is the pragmatic open choice.

## Roles

| Component | Role |
|---|---|
| **Strix** | Household server — brain, model host, orchestrator, ADB TV control |
| **Mini-PC + screen** (per room) | Thin client + local wake/fallback |
| **Web/PWA remote** | Universal control surface (any device) |
| **Fire TV remote app** | Precision streaming navigation (complement, not replace) |

## Open questions / next steps

- [ ] Prove the multi-room pattern: add a second mini-PC + screen as a second room
- [ ] Decide the local-fallback model size (0.5B vs 4B) per room
- [ ] Wire the web remote to the household server for multi-room routing
- [ ] Revisit Android edge device for deeper agentic control (open-hardware path)
