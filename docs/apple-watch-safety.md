# Apple Watch Safety Integration — GA/Jeeves (2026-08-14)

**Purpose:** Spec how GA layers a **household alert + Elder Brain log** on top of the Apple
Watch's built-in Fall Detection / Emergency SOS, so a fall not only auto-calls 911 (Apple's
job) but also notifies the household and records the event for Jeeves.

**Owner:** Tom · **Device:** Apple Watch Series 11 (in hand, watchOS 27, Siri-AI capable)

---

## 1. The division of responsibility (honest)

Apple's watch already handles the **life-safety core** — GA must NOT duplicate or interfere:

| Layer | Who | What |
|---|---|---|
| **Fall Detection** | Apple (built-in) | Detect hard fall → if immobile ~1min → 30s countdown → **auto-call 911**, play recorded message w/ location + Medical ID, text emergency contacts. Satellite fallback. |
| **Emergency SOS** | Apple (built-in) | Side-button hold → emergency call, even locked / Silent Mode. |
| **Medical ID** | Apple (built-in) | Available from lock screen for first responders. |
| **Household alert** | **GA (this spec)** | On a fall event, notify the household (family, room terminals) + log to Elder Brain. |
| **Voice orchestration** | **GA (this spec)** | "Jeeves, I've fallen" → Jeeves coordinates family call + context. |

GA's value-add is the **household + memory layer** — Apple notifies 911 and emergency contacts;
GA notifies the *household* and remembers the event for Jeeves's context.

## 2. The API: `CMFallDetectionManager` (verified)

Apple exposes **`CMFallDetectionManager`** (Core Motion) — a third-party watchOS app can:
- Request the user's authorization
- Set a delegate to receive **fall-detection notifications**

Entitlement: `com.apple.developer.health.fall-detection` ("Fall Detection Notifications").

**So a small GA watchOS companion app can receive fall events and forward them to the MBP/GA
server** (over the same Tailscale/WebSocket path GA already uses). This is the integration hook.

**Caveat (honest):** the API is real but adoption is thin ("haven't seen any app that uses it").
It requires a watchOS app + the entitlement (needs Apple approval for the entitlement). This is
a real build, not a config toggle.

## 3. Architecture

```
Apple Watch (Series 11)
  ├─ Built-in Fall Detection → auto-911 + emergency contacts (Apple, untouched)
  └─ GA watchOS companion app (CMFallDetectionManager delegate)
        └─ fall event → WebSocket/Tailscale → MBP GA server
              ├─ Notify household: family iMessage, room terminals ("Tom's watch
              │   detected a fall — is everyone OK?")
              └─ Log to Elder Brain: fall event, time, location, context
                    → Jeeves can reference it later ("you had a fall Tuesday")
```

## 4. What GA does on a fall event

1. **Receive** the fall notification from the watch app (CMFallDetectionManager delegate).
2. **Notify the household** — family members (iMessage), room terminals (spoken alert).
   Frequency-capped, context-gated (don't spam if Apple already called 911).
3. **Log to Elder Brain** — timestamp, location, whether Apple auto-called 911, any context.
4. **Jeeves voice path** — if the senior says "Jeeves, I've fallen," Jeeves coordinates a family
   call + reassurance, complementing the automatic 911.

## 5. Build checklist

- [ ] watchOS companion app (GA Watch) with `CMFallDetectionManager` delegate + entitlement
- [ ] WebSocket/Tailscale link from watch app → MBP GA server (reuse existing transport)
- [ ] GA server handler: on fall event → household notify + Elder Brain log
- [ ] Household notification channel (iMessage to family, room-terminal spoken alert)
- [ ] Elder Brain log schema for safety events
- [ ] Jeeves "I've fallen" intent → family-call orchestration
- [ ] Privacy: fall events are sensitive — local-first, never leave MBP without consent
      (same class as viewing data)

## 6. Immediate (no-build) deployment of the watch itself

Even before the GA companion app, the **watch alone** is the safety net. Configure now:
- **Fall Detection ON** (Settings → SOS → Fall Detection)
- **Medical ID** set up (Health app) with health info + emergency contacts
- **Share During Emergency Call** ON
- **Wrist Detection ON** (required for auto-911)
- **Emergency SOS** side-button configured

## 7. Honest expectations

- The **watch's built-in Fall Detection is the real safety net** — deploy it now, zero build.
- The **GA household-alert layer is a real build** (watchOS app + entitlement + server handler),
  and the `CMFallDetectionManager` entitlement needs Apple approval. Worth doing, but it's a
  follow-on, not a prerequisite.
- **Siri AI on the watch** (Series 9+) needs the paired iPhone to be AI-enabled — the household's
  iPhone 13s aren't, so on-watch Siri AI is gated until a newer iPhone exists. Fall Detection is
  NOT gated by this.

## 8. Watch items

- Confirm `CMFallDetectionManager` entitlement approval path (Apple Developer).
- Whether watchOS 27 adds richer HealthKit fall/emergency event exposure.
- Test the fall-event → household-notify path once the companion app is built.
