# Home-Map Scan App (RoomPlan) — Requirements & Build Plan

**Status:** DRAFT — ready to build when Xcode supports iOS 27 (blocker: needs to
target the iOS 27 beta SDK). This doc is the spec for the iPad scanning app and
how it hands the home model to GA-V9 / Jeeves.

**Date:** 2026-08-13 · **Owner:** Tom · **Device:** iPad Pro (LiDAR), iOS 27 beta
(also runs on iOS 16+ / iPad Pro 2020+).

---

## 1. Why

Turn one-time, interactive room scans into a **persistent home model** so every
future dimensional question ("price carpet for the living room", "total floor
area", "will this fit?") is a lookup, not a re-measurement. Aligns with the
"Jeeves as primary app / be prepared, not naggy" vision: map once, query forever.

## 2. Key facts (verified against Apple docs / community, 2026-08-13)

- **RoomPlan framework** (`RoomCaptureSession`, `RoomBuilder`, `CapturedRoom`)
  builds a structured room model from LiDAR scans. **Requires a LiDAR device**:
  iPad Pro 2020+, iPhone 12 Pro+; min iOS 16.0.
- **`CapturedRoom` is `Codable`** → export as JSON. Each **Surface** (wall,
  floor, door, window, opening) and **Object** (table, sofa, bed, stove, ...)
  carries:
  - `dimensions` (meters, width × height × depth)
  - `transform` (position + rotation)
  - `category`
  - `identifier` / `parentIdentifier`
  - `polygonCorners` (2D polygon for walls/floors)
- **`StructureBuilder`** (WWDC23, iOS 17+) merges multiple `CapturedRoom`s into
  a **`CapturedStructure`** = whole-home model with **labeled sections**
  (`livingRoom`, `bedroom`, `bathroom`, `kitchen`, `diningRoom`,
  `unidentified`) + per-section `center` and `story` (floor level). **This is
  the piece that makes "map the entire home" natural.**
- USDZ 3D export also available (`CapturedRoom.export(to:)`) for visual review.
- Caveat: `polygonCorners` non-empty means a non-rectangular surface — floor
  area for carpet pricing should use the polygon area, not just width×depth.

## 3. What the app does (user flow)

A small, single-purpose iPad app ("Home Map"). Not a RoomPlan demo — minimal,
focused, and built to hand data to GA.

1. **New scan** — pick a room (or "unknown"): name it (e.g. "Living Room",
   "Master Bedroom"). Optional: assign it to a story/floor.
2. **Scan** — full-screen `RoomCaptureView`; user walks the room pointing the
   iPad at surfaces. Standard RoomPlan flow: live preview → finish → process
   with `RoomBuilder`.
3. **Review** — show the captured room (3D/2D), dimensions, detected objects;
   let the user rename the room, split a mis-merged room, or re-scan.
4. **Export** — when all rooms for the home are scanned:
   - `StructureBuilder` merges all `CapturedRoom`s → `CapturedStructure`
   - Export as **JSON** (`CapturedStructure`/`CapturedRoom` are Codable)
   - Deliver to the MBP (see §5 transport)
   - Keep a local copy on the iPad (Files / app sandbox) as backup.

## 4. Data model (the home model GA stores)

The exported JSON is the **source of truth**. Store it in the Elder Brain as
`~/elder_brain/home_model/` (local-first, privacy ✓ — geometry never leaves the
MBP without explicit permission).

```jsonc
{
  "captured_at": "2026-08-13T18:00:00Z",
  "device": "iPad Pro (12.9-inch)",
  "structure": {
    // CapturedStructure: array of sections (rooms), each labeled
    "sections": [
      {
        "label": "livingRoom",      // livingRoom|bedroom|bathroom|kitchen|diningRoom|unidentified
        "room_name": "Living Room", // user-assigned display name (authoritative)
        "story": 0,
        "center": [x, y, z],
        // CapturedRoom content for this section:
        "surfaces": [
          { "category": "floor", "dimensions": [5.2, 0, 4.1],
            "polygonCorners": [[0,0,0],[5.2,0,0],[5.2,0,4.1],[0,0,4.1]],
            "transform": [ ...16 floats... ] },
          { "category": "wall", "dimensions": [5.2, 2.7, 0], ... },
          { "category": "door", ... }, { "category": "window", ... }
        ],
        "objects": [
          { "category": "table", "dimensions": [1.6, 0.75, 0.9], "transform": [...] }
        ]
      }
    ]
  }
}
```

## 5. Transport: iPad → MBP (pick ONE primary + a fallback)

| Method | How | Notes |
|---|---|---|
| **Tailscale + HTTP POST** (preferred) | App POSTs the JSON to the GA receiver (`:8787`, like the iPhone bridge) | Same transport GA already uses; device already on the network. Add `/home-model` endpoint. |
| **AirDrop / Files** | Export JSON to Files, AirDrop to MBP | Good manual fallback / one-off |
| **iCloud Drive** | App writes to an iCloud folder GA watches | Less preferred (sync latency, privacy) |

Primary recommendation: **Tailscale POST to the GA receiver**, matching the
existing iPhone bridge pattern (receiver already runs at `http://100.85.123.9:8787`).

## 6. Jeeves orchestration (how the model is used)

- **Ingest:** on export, validate the JSON, merge into `home_model/`, index by
  room name.
- **Query:** a `home_tools.py` (GA-V9) exposes:
  - `room_area(room)` → floor area (polygon area of the floor surface, m²)
  - `room_dimensions(room)` → length × width (meters/feet)
  - `list_rooms()` → names + areas
  - `home_totals()` → total floor area
- **Scenario flow (carpet):**
  Jeeves: *"Let me use the home map. Living Room is ~21.3 m², Master Bedroom
  ~15.8 m². Add 10% waste → 40.8 m² ≈ 439 sq ft. Carpet at $3.50/sq ft → about
  $1,540 installed. Want me to find local installers or add it to a note?"*

## 6b. Furnishings inventory + 3D rearrangement (the "rearrange without moving")

**Goal:** a database of current furnishings & locations (with photos) that lets
Jeeves/user rearrange furniture/accessories in 3D space *virtually* — nothing
physically moved.

**Key fact:** RoomPlan ALREADY detects furniture objects — table, sofa, bed,
chair, stove, etc. — each with dimensions (meters), position, rotation, and
category, exported as `CapturedRoom.Object`. So the furnishings DB is largely a
**byproduct of the home scan**, not a separate effort. We add: a photo per item
(camera stack already built), a human label ("the blue armchair", "Grandma's
coffee table"), and an item→room association.

### Data model (extends §4)

```jsonc
{
  "id": "obj-17",
  "category": "table",
  "label": "blue armchair",          // user-assigned (authoritative for queries)
  "room": "livingRoom",              // section id/label
  "dimensions": [1.6, 0.75, 0.9],    // meters
  "transform": [...16 floats...],    // position + rotation from scan
  "photo": "/home_model/photos/livingroom-armchair.jpg",  // captured via camera
  "usdz_model": "/home_model/usdz/livingroom.usdz",       // optional per-item 3D
  "notes": ""
}
```

Stored under `~/elder_brain/home_model/furnishings.json` + `photos/` + `usdz/`.
Local-first, same privacy class as geometry.

### Tiered plan (honest — the editor is the big one)

| Tier | Capability | Effort | Notes |
|---|---|---|---|
| **T1 (now/reuse)** | Furnishings DB: scan objects + photos + labels + room assoc | Low | Reuses RoomPlan + camera stack |
| **T2 (medium)** | USDZ export → "view this room in 3D/AR" via AR Quick Look on the iPad | Low-Med | Free; RoomPlan exports USDZ |
| **T3 (the build)** | 3D rearrangement editor (drag, fit-check, preview) | **High** | Two candidate engines — see below |

### T3 engine decision (deferred — do not commit yet)

- **Blender headless (`bpy`) as the engine** — the "dumb-down Blender" idea.
  Blender runs headless in the background; Jeeves calls a bpy script to import
  room geometry + furniture, reposition objects programmatically, and render a
  photorealistic preview. The senior-facing UI (Flutter/voice) stays simple and
  never shows Blender. Most powerful + best rendering. Costs: not yet installed
  (~300MB cask), bpy scripting + render pipeline is real work, and the *input*
  ("move the couch to the west wall") must be mapped to scripted operations.
- **Lighter web route (Three.js)** — import RoomPlan JSON, drag furniture in a
  top-down/3D browser view, check fit/collisions. Far simpler, runs anywhere the
  phone/browser is, less photoreal.

**Recommendation:** verify the Three.js/web path first — the core goal
(rearrange + fit-check without moving) is what it does well and cheaply. Only if
it proves too limited (fit-checking, realism) do we upgrade to Blender headless.
Record the DB + tiers now; decide the editor engine when we reach T3.

## 7. Build checklist (when Xcode unlocks iOS 27)

- [ ] Create minimal SwiftUI iPad app target ("Home Map"), iOS 17+ (for
      `StructureBuilder`)
- [ ] `RoomCaptureView` full-screen scanning UI + `RoomCaptureSession.delegate`
- [ ] `RoomBuilder` processing → review screen (3D + dims + objects)
- [ ] Room naming + story assignment; "add another room" flow
- [ ] `StructureBuilder.capturedStructure(from:)` merge across rooms
- [ ] Export `CapturedStructure` → JSON (Codable) + optional USDZ
- [ ] Transport: Tailscale POST to GA receiver `/home-model`
- [ ] GA-V9 `home_tools.py`: ingest + `room_area`/`room_dimensions`/`list_rooms`
- [ ] Jeeves intent fast-path for "how big is", "price carpet", "total area"
- [ ] Polygon-area computation for non-rectangular floors (carpet waste)
- [ ] **Furnishings DB (T1):** scan objects → `furnishings.json`; photo-per-item
      via camera; labels + room association
- [ ] **T2:** USDZ export → AR Quick Look "view room in 3D" on the iPad
- [ ] **T3 (deferred decision):** Three.js web editor first; Blender headless as
      upgrade — decide engine at T3, do not pre-commit

## 8. Privacy

- Home geometry is **sensitive**. Scan data stays **on the MBP** (Elder Brain),
  never synced to cloud, never sent off-device without explicit permission.
- Matches the existing rule: viewing/screen data never leaves the MBP without
  explicit user consent. Home layout is the same class of data.
- The scan app itself does the LiDAR capture on the iPad (on-device), then only
  the abstracted JSON travels to the MBP over the trusted Tailscale link.

## 9. Sequencing / honest expectations

1. **Now (no blockers):** voice Q&A carpet flow (Jeeves asks dims, computes,
   prices). Delivers value today, proves the interaction.
2. **When Xcode supports iOS 27:** build the Home Map app (this doc) — a small,
   contained build; RoomPlan does the heavy lifting.
3. **Then:** Jeeves orchestrates the mapping session, ingests the JSON, and
   every dimensional question becomes a lookup.

**Watch item:** revisit `iphone-imessage-control` / iOS-27 status when Xcode
catches up — that gate unblocks BOTH the scan-app build (Xcode target) and full
phone control (WDA).
