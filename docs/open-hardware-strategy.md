# Open Hardware Strategy — GA Device Decision Record (2026-08-15)

**Purpose:** Capture the research on running GA on open hardware, driven by repeated
friction with Apple's closed toolchain (entitlement gates, provisioning, the Flutter/watch
companion cycle — all "should work but doesn't"). Records the decision: **Android tablet for
testing/dev now, keep the iPhone 13, defer the phone upgrade.**

**Owner:** Tom · **Budget:** ~$2,500

---

## 1. The trigger (why this exists)

Repeated Apple "should work but doesn't" walls:
- WDA needed Xcode + entitlement + provisioning + tunnel + running test
- `xcodebuild` can't auto-provision new capabilities (GUI-only pass)
- **Flutter + watchOS companion target = build cycle** (dead end for the watch relay)
- Siri AI gated by A17 Pro hardware (iPhone 13 gets nothing)
- Watch `appInstalled: NO` — companion only registered via the embed that cycles

**The honest core lesson:** when closed tooling breaks, you're blocked by a gatekeeper.
GA's *core* (server, LLMs, Elder Brain, room terminals) is already open. The only closed
part is the Apple client. The question was whether to keep it.

## 2. Android tablet — DO IT NOW (the decision)

**Use a cheap Android tablet as the GA test/dev bed + room-terminal prototype.**

| Candidate | Price | Why |
|---|---|---|
| Galaxy Tab A9+ | ~$200-250 | Budget king, 90Hz, 11", great dev device |
| Tab A1 Plus | ~$250 | 12.2" bigger screen |
| Tab S10 FE | ~$400 | Wirecutter "best overall" midrange |

**Why this is the right first move:**
- **No gatekeeper** — ADB, sideload, Termux, no provisioning hell. Iterate the GA client freely.
- **Doubles as a room-terminal prototype** ("smart speaker with screens").
- **Low cost / low risk** — a test bed, not a commitment.
- **No Android tablet matches the iPad for LiDAR** (home-mapping) — but that's a separate concern.

## 3. Keep the iPhone 13 (the decision)

- Already works as a GA voice client (verified: 5.3s roundtrip voice loop).
- **"Talk to Jeeves" Siri App Intent** built + compiling — gives voice entry from any device.
- iOS 27 = WDA touch control works.
- No Siri AI (A15 < A17 Pro), but **GA doesn't need it** — GA runs its own voice stack.
- Zero cost to keep.

## 4. Phone upgrade — DEFER (the decision)

Neither current option is a no-brainer:

| | iPhone 18 Pro / Siri AI | Pixel 11 Pro / Gemini |
|---|---|---|
| Available now? | ❌ Sept 2026 | ✅ Now |
| On-device AI | Siri AI (A17 Pro+ gate) | Gemini Nano (3.5x faster) |
| Offline reliability | N/A (beta) | ❌ cloud-dependent |
| Latency | Unknown | ⚠️ slower on complex |
| Openness / GA control | ❌ locked | ✅ ADB/sideload/Termux |
| Durability | unknown | ⚠️ smaller Pro = "B" rating (get XL) |
| Price | $1,099-1,299+ | $1,099 |

**Key findings:**
- **Siri AI is beta-buggy** (real report: "won't stop an alarm by voice, needs unlock") + pricing rising + not out yet.
- **Gemini is cloud-dependent** (against GA's local-first/privacy) + slower + forced migration from Assistant.
- **The sharpest insight:** neither phone's *built-in AI* matters to GA — **GA runs its own voice stack.** So the phone decision should hinge on **openness/controllability**, not the bundled assistant.

**Defer** until: iOS 27 Siri AI ships stable AND is testable, OR a need for an open daily-driver phone emerges.

## 5. The future open stack (when ready)

```
Pixel 11 Pro / XL ($1,099-1,299)  — the open GA phone (Gemini, controllable)
Pixel Watch 5 LTE (~$499)         — always-on voice/emergency, standalone SIM
Android tablet (~$250)            — test bed + room terminal
                                ≈ $1,850 of $2,500 budget
```

- **Pixel Watch 5 LTE** directly fixes the Apple Watch failure: standalone SIM (works outside
  without the phone), open Wear OS (no companion-embedding cycle), the "talk to Jeeves" relay is
  trivial. Needs an Android phone as companion → aligns with the Pixel phone.
- **Android tablets** replace the iPad for the *open* client/terminal roles.
- **Keep the iPad ONLY for LiDAR home-mapping** (its one irreplaceable GA value; no Android has LiDAR).

## 6. Decision log

1. **Android tablet for testing/dev now** — low cost, no gatekeeper, doubles as room terminal.
2. **Keep the iPhone 13** — works, zero cost, "Talk to Jeeves" intent covers voice entry.
3. **Defer the phone upgrade** — neither Siri AI nor Gemini is compelling for GA; phone AI is
   irrelevant since GA runs its own stack.
4. **Open hardware = Android** (Pixel phone + watch + tablets) when the upgrade happens.
5. **iPad kept only for LiDAR home-mapping** — not replaceable on Android.

## 7. Watch items
- When iOS 27 Siri AI ships stable, re-test on a capable device before any iPhone upgrade.
- Monitor postmarketOS (the "own the OS" dream) as a research track, not the plan.
- The Android tablet, once bought, is the primary GA-client test bed.
