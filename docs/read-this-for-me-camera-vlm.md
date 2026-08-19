# Read-This-for-Me — camera + local VLM understanding

**Status:** DRAFT — builds on the EXISTING GA camera feature (camera icon in the
GA app, `old-ios/GeezerAid`), extending it from "OCR text → read aloud" to
"understand the image → read + interpret." Local-first, no new hardware.

**Date:** 2026-08-13 · **Owner:** Tom

---

## 1. Why

Small print is one of the biggest daily frustrations for seniors: pill bottles,
nutrition labels, letters, appliance settings, instructions. The camera feature
already exists (camera icon in the GA app) but today it only does **raw OCR →
read the text**. We have a proven **local VLM** (`:8086`, `unsloth/Qwen3.5-9B`,
multimodal) that can *understand* an image, not just dump its text. This doc is
the plan to connect the two so Jeeves can **read AND interpret** ("this is a
prescription bottle: 1 tablet twice daily, expires 2027, take with food").

## 2. What exists today (verified in code)

- **UI:** camera icon → `CameraView` (SwiftUI `UIViewControllerRepresentable`,
  `UIImagePickerController`, `sourceType = .camera`, `.photo`) in
  `old-ios/GeezerAid/ContentView.swift`.
- **OCR:** `performOCR(on:)` uses Apple Vision `VNRecognizeTextRequest`
  (`.accurate`, on-device) → joined text string.
- **Flow:** `handleCapturedImage(image)` → `performOCR` → if text found, sends
  to server as: *"The user showed me this text and wants me to read it aloud:\n
  <extracted>"* → Jeeves speaks it.
- **Limits:** (a) only raw TEXT reaches the server — the image is discarded;
  (b) no interpretation (dosage, expiry, instructions, "what is this");
  (c) OCR can garble small/layout-heavy text that a VLM would read correctly.

## 3. The enhancement: image → local VLM understanding

Keep the camera capture + on-device OCR as a fast local fallback, but add a
**primary path that sends the image to the local VLM** for real understanding.

### New flow
1. User taps **camera icon** → captures photo (unchanged).
2. GA app sends the **image bytes** (base64 PNG/JPEG) to the GA server
   (`server_v9.py`) — NOT just OCR text.
3. Server runs the image through the **local `:8086` VLM** with a read/interpret
   prompt (same call as `tv_adb.describe_screen` / `iphone_core.describe`).
4. Jeeves returns a natural spoken answer: read the text AND explain what it is
   and what matters (dosage, expiry, size, instructions, next steps).
5. Optional: also run on-device OCR; if the VLM is down, fall back to the OCR
   text path (graceful degradation — today's behavior).

### Prompt template (server side)
```
The user took a photo and wants help reading/understanding it.
Describe the text on it, identify what it is (pill bottle, label, letter,
appliance, receipt...), and call out anything important (dosage, expiry,
measurements, instructions, prices). Be accurate and plain-spoken.
Be explicit if the image is unclear or you cannot read part of it — do NOT
invent dosage/medical details you cannot verify.
```

### Honest boundaries (flagged)
- **Medication:** we can READ and LABEL (identify the bottle, the printed
  dosage). We must NOT give medical advice ("should I take this with food") or
  second-guess a prescriber. Jeeves says what the label says; anything beyond is
  "ask your doctor/pharmacist." A known-meds list in the Elder Brain could later
  cross-check ("this matches your prescribed amlodipine"), but never advise.
- **Sensitive content:** the photo is private — processed on-device → local
  MBP VLM, never leaves the MBP without explicit permission (same rule as
  viewing/screen data). Raw photos should not be retained longer than needed.

## 4. Server-side integration (GA-V9)

Add to `server_v9.py` a handler for an image/photo upload:
- New endpoint (or reuse the chat handler with a `data:image/...;base64,` body)
  accepting `{image_b64, prompt?}`.
- Calls the local VLM (`http://127.0.0.1:8086/v1/chat/completions`,
  `unsloth/Qwen3.5-9B`, image_url base64) — **reuse `tv_adb`/`iphone_core`
  describe logic**; factor a shared `vlm_describe_image(path_or_b64, prompt)`
  helper so all callers stay consistent.
- Returns the VLM's description as the spoken answer; optional `actions`
  (e.g. a "save to notes" chip).

`tools/` already has the pattern: `tv_adb.describe_screen` and
`iphone_core._describe` both do base64→`:8086`. Extract a shared helper.

## 5. iOS app changes (old-ios/GeezerAid)

- Keep `CameraView` + on-device OCR (fast fallback, offline-capable).
- `handleCapturedImage`: **send the image bytes** (base64) to the server in
  addition to (or instead of) the OCR text; let the server choose
  VLM-first, OCR-fallback.
- Add a lightweight "Reading..." → "Got it, asking Jeeves..." state (mostly
  exists).
- No new permissions (NSCameraUsageDescription already present).

## 6. Sequencing

1. **Now (no blockers):** add the server `/photo`-style VLM handler (reuse the
   proven `:8086` call); wire the GA app to send the image base64. This is a
   contained change using pieces we've already validated. The camera app side
   can keep OCR as fallback.
2. **Test:** snap a pill bottle / nutrition label / letter; confirm Jeeves reads
   + interprets accurately; confirm graceful fallback when VLM is down.
3. **Later:** known-meds cross-check (Elder Brain list) — design the clinical
   boundary first; home-inventory tagging (from RoomScan) for "where is X".

## 7. Privacy (same class as viewing data)

- Photo processed on-device → local MBP VLM; nothing leaves the MBP without
  explicit permission.
- Don't persist raw photos beyond the request (transient in-memory/tmp).
- Matches the standing rule: user data stays on the MBP.

## 8. Open questions for Tom

- **Image size:** downsample to ~2MP before sending (VLM handles it, less
  upload) — confirm acceptable.
- **Retention:** OK to keep nothing after answering (no photo log)? Recommend yes.
- **Camera app location:** enhance `old-ios` (current) or fold into a newer
  `new-ios`/Flutter client? Recommend old-ios for now (it's what has the camera).
