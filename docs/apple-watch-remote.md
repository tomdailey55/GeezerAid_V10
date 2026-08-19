# Apple Watch as GA Remote — Auth + Input + Safety (2026-08-14)

**Purpose:** The Apple Watch (Series 11, in hand) is the **single on-body token** that
authenticates the user, provides hands-free input to GA, receives alerts, and handles safety.
It turns GA from a "talk to a box in the room" assistant into a "talk to the thing on your
wrist" assistant — ideal for a senior, especially one with limited mobility.

**Owner:** Tom · **Device:** Apple Watch Series 11 (watchOS 27, Siri-AI capable, Fall Detection)

---

## 1. The core insight

The watch is the **one device always on the body, always awake, already passcode-secured.**
That makes it the natural **remote control + authentication token** for a household assistant
that lives on the MBP (brain) and iPad (display). It is NOT a bypass — it is Apple's own
authenticated path, because the watch itself is the secured device.

## 2. The three roles

### A. Authenticate (unlock the devices) — Apple-native, works today
- **Unlock Mac with Apple Watch** — first-class macOS feature: watch is passcode-gated, on-body,
  same Apple ID + 2FA → auto-unlocks when nearby. Also approves admin-password requests
  (double-click side button).
- **Unlock iPhone/iPad with Apple Watch** — same mechanism (same Apple ID, Bluetooth range).
- **Why this is legitimate (not a bypass):** the watch's PIN gates everything. The security
  boundary is preserved — the watch IS the authenticated device. This is the right unlock path
  for an immobile senior who can't reach the iPad or type a passcode.
- **Setup requirement:** all devices signed into the same Apple ID with 2FA; watch has a passcode.

### B. Input (control GA hands-free) — mixed native + GA build
- **Voice → Jeeves:** GA's own voice stack (Flutter client / wake word) — works today, no Siri AI.
  "Jeeves, play the news on the TV."
- **Double Tap gesture (watchOS 27):** dismiss notifications, decline calls, navigate — hands-free.
  watchOS 27 adds a new tap gesture for this. Native, works today.
- **Complications / Shortcuts:** one-tap GA actions on the watch face (TV on/off, Weather,
  "I'm OK", family call). GA build (Shortcuts now; watchOS app later).
- **Siri AI voice remote (future):** on-watch Siri AI (Series 9+) reaches into GA via App Intents
  — "ride don't fight." Gated by the paired iPhone being AI-enabled (13s aren't; revisit at
  stable iOS 27 with a newer iPhone).

### C. Safety — Apple-native, works today
- **Fall Detection:** hard fall → if immobile ~1min → 30s countdown → auto-911 + recorded message
  w/ location + Medical ID → text emergency contacts. Satellite fallback.
- **Emergency SOS:** side-button hold → emergency call, even locked / Silent Mode.
- **Medical ID:** available from lock screen for first responders.
- **GA layer (build):** `CMFallDetectionManager` companion app → forward fall events → household
  alert + Elder Brain log (see `apple-watch-safety.md`).

## 3. Architecture

```
Apple Watch (on-body token)
   ├─ AUTH: unlock Mac / iPhone / iPad (Apple native, same Apple ID + 2FA)
   ├─ INPUT: voice→Jeeves, Double Tap (dismiss/navigate), complications, Siri AI (future)
   ├─ ALERT: haptic nudges from GA ("dinner's ready", "Tom's watch detected a fall")
   └─ SAFETY: Fall Detection / SOS / Medical ID
        │
        ▼
   MBP (GA brain) — intent, Elder Brain, device orchestration
        │
        ├─ Fire TV / room terminals (actuators)
        └─ iPad (display) — unlocked by the watch, shows Jeeves's work
```

## 4. The senior experience (the point)

- **Immobile senior:** watch on wrist → iPad unlocks automatically (no reaching/typing) → says
  "Jeeves, I've fallen" → Jeeves coordinates family call + reassurance, while the watch's Fall
  Detection auto-calls 911. Double-tap dismisses any notification hands-free.
- **Able-bodied senior:** watch is the quick remote — raise wrist, tap a complication, talk to
  Jeeves, get a haptic nudge when dinner's ready.

## 5. Phased build

| Phase | What | Effort | Gate |
|---|---|---|---|
| **0 (now, no build)** | Configure watch: passcode, Fall Detection ON, Medical ID + emergency contacts, wrist detection, Double Tap, Auto Unlock on Mac/iPad | None | Setup |
| **1 (short-term)** | GA watchOS companion app: complications + haptic nudges + fall-event forwarding (`CMFallDetectionManager`) | Real build | Entitlement approval |
| **2 (later)** | Siri AI voice remote via App Intents (needs AI-enabled iPhone) | Build | Newer iPhone |

## 6. Honest constraints

- **Siri AI on watch** gated by paired iPhone (13s aren't AI-enabled). Shortcuts + complications
  + Double Tap work today without it.
- **Watch is a thin client** — input/output only; MBP does the thinking. Correct division.
- **Battery** — daily charge. Acceptable.
- **Auto Unlock** needs same Apple ID + 2FA across devices (setup, not a blocker).

## 7. Watch items

- Confirm watch-based unlock for iPad/iPhone in iOS 27 (9to5mac confirms it works; verify on the
  household's devices once iPhone is on iOS 27).
- `CMFallDetectionManager` entitlement approval path.
- watchOS 27 Double Tap gesture specifics for GA actions.
