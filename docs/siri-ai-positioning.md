# Siri AI Positioning — GA vs. Apple's Agentic Assistant (2026-08-14)

**Purpose:** Capture the research on iOS 27 / watchOS 27 Siri AI (App Intents API, real-world
reliability, hardware gates) and GA's strategic positioning against it. Decides where GA
concentrates vs. where Apple's Siri AI should own the experience.

**Owner:** Tom · **Date:** 2026-08-14

---

## 1. The headline

Apple's **Siri AI** (iOS 27 / watchOS 27 / macOS 27, WWDC26) is a genuine, agentic, on-device
assistant — on-screen awareness, cross-app actions, semantic content search, ~5s conversational
answers. Early reviews are strong ("it bloody works"). **This converges on GA's "Jeeves makes it
happen" vision for generic single-device assistance.**

**Strategy: don't fight Siri AI on generic turf — concentrate GA on what Apple won't build.**
GA's durable moat is **household orchestration + the Elder Brain + proactive suggestions +
non-Apple-device control**. Let Siri AI own the personal on-device assistant layer; GA owns the
household brain + cross-device orchestrator.

## 2. The hardware gate (decisive for this household)

**iOS 27 runs on iPhone 11+, but Siri AI requires:**
> iPhone 16 models or later, iPhone 15 Pro / Pro Max, iPad mini (A17 Pro), M1+ Macs,
> Apple Watch Series 9+, Ultra 2+, SE 3 (paired with an AI-enabled iPhone nearby).

| Device in household | iOS 27 | Siri AI |
|---|---|---|
| iPhone 13 (A15) | ✅ | ❌ **NOT supported** |
| iPad Pro (iOS 27 beta) | ✅ | ✅ (M1) |
| MacBook Pro M1 Max (MBP) | ✅ | ✅ |
| **Apple Watch Series 11 (in hand)** | ✅ watchOS | ✅ (Series 9+) |

**Implication:** the household's **iPhone 13s cannot run Siri AI**. To get Siri AI on the phone,
upgrade to iPhone 15 Pro / 16+. The **Apple Watch Series 11 already in hand is Siri-AI capable**
(needs the paired iPhone to also be AI-enabled for on-watch Siri AI).

## 3. Real-world Siri AI reliability (as of 2026-08, beta)

- **Strong:** finds content across Messages/Mail/Photos/Notes/Calendar (even OCR in a photo),
  on-screen awareness works, ~5s natural conversational answers. "Nothing short of brilliant" /
  "it bloody works."
- **Caveats (beta):** battery drain, needs occasional device restarts, a reported privacy-leak
  bug (LLM prompt dump in error reporting), "just good enough to ease its AI crisis" per one
  sober Reddit take. Wirecutter: "inevitably have bugs and cause battery drain."
- **Gate:** English-only initially, beta first.

**Honest call:** do NOT upgrade iPhones *just* for Siri AI yet. It's beta; the iPhone 13s are
blocked by hardware; and GA fills the household need today. Revisit when iOS 27 ships stable and
a newer device is testable.

## 4. The App Intents API surface (what GA can hook into)

Siri AI's developer foundation is **App Intents** (Apple Intelligence). Three pillars:
- **App Entities** — structured content Siri can search/resolve ("find that recipe")
- **App Intents / App Schemas** — actions Siri can invoke; schema domains make it fluent
- **On-Screen Awareness** — annotate views so Siri resolves "this message", "the third one"

Useful specifics:
- **Donations** — GA can donate UI actions as schema-conforming intents; Apple Intelligence learns
  GA's patterns with no GA-side NLU.
- **IntentValueQuery + in-app search** — make Elder Brain content (recipes, notes) Siri-searchable.
- **`appEntityIdentifiers`** — attach entities to notifications/Now Playing/AlarmKit so Siri acts
  on system integrations GA uses.
- **`LongRunningIntent`** — background work past 30s (long GA operations).
- **AppIntentsTesting** — validation framework.

**Play:** expose GA actions + Elder Brain content as App Intents so Siri AI can reach INTO GA —
"Siri, tell Jeeves to open the Weather app" / "find my lasagna recipe." GA gets Apple's NLU
for free; Apple doesn't have to understand GA's internals. **Ride Siri AI, don't fight it.**

## 5. The GA moat (what Siri AI can't/won't do)

| Capability | Siri AI | GA/Jeeves |
|---|---|---|
| Drive **non-Apple devices** (Fire TV, room terminals) | ❌ | ✅ ADB/Cast/WebSocket orchestration |
| Hold **household memory** (Elder Brain: recipes, notes, history) | ❌ personal-only | ✅ persistent household vault |
| **Proactive** suggestions ("be prepared, not naggy") | ❌ reactive | ✅ recommendations, viewing-aware |
| Run on **iPhone 13s** (household's actual phones) | ❌ | ✅ server-driven, device-agnostic |
| **Cross-device orchestration** (TV+phone+watch+room together) | ❌ per-device | ✅ the north star |

## 6. Apple Watch — the safety net (independent of Siri AI)

- **Fall Detection works on Series 4+, SE+** — NOT gated by Siri AI. Detects a hard fall, and if
  immobile ~1 min → 30s countdown → **auto-calls 911**, plays a recorded message with location +
  Medical ID, then texts emergency contacts. Satellite fallback (Ultra 3 / iPhone 14+).
- **Apple Watch Series 11 (in hand)** supports Fall Detection fully.
- **Emergency SOS** (side button) works even locked / Silent Mode.
- **Medical ID** available from lock screen — first responders get critical info.

**The watch (already owned) is the no-regret, immediately-deployable safety layer** for an
immobile/handicapped senior — no iPhone upgrade needed for Fall Detection.

## 7. Recommended roadmap

1. **Do not** upgrade iPhones for Siri AI now (beta + A15 gate). Revisit at stable iOS 27.
2. **Deploy the Apple Watch Series 11** as the safety layer: enable Fall Detection, set up Medical
   ID + emergency contacts + Share During Emergency Call, wrist detection ON.
3. **GA integration:** monitor Fall Detection / Health events → notify household + log to Elder
   Brain (complementing the auto-911). (See the Apple Watch safety spec.)
4. **Position GA** on the moat (household orchestration + Elder Brain + proactive + non-Apple).
5. **Future (when a Siri-AI-capable iPhone exists):** expose GA actions + Elder Brain content as
   App Intents so Siri AI can reach into GA ("ride don't fight").

## 8. Watch items

- iOS 27 Siri AI stable release + English GA rollout timing.
- Whether watchOS 27 exposes Fall Detection / HealthKit events to third-party apps (for the
  household-alert integration) — research when building the watch safety spec.
- Siri AI's third-party App Intents maturity (currently "only native Apple apps" per one report).
