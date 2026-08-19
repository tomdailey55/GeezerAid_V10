# GA-V9 Server — Deployment, Services & Operations

How the GeezerAid V9 backend is actually run on the MBP, what services are
wired, and how to recover/modify it. Written after the 2026-07-26 TTS outage
debug — read this before touching the server.

## Which server does the iPad Flutter app use?

**`~/Public/GA-V9/server_v9.py`** — a stdlib `http.server`, supervised by
launchd as **`com.geezeraid.server-v9`**.

- Bound to `0.0.0.0:8765` (`GA_PORT`/`GA_HOST` in the plist).
- Flutter hits `http://100.85.123.9:8765/...` (Tailscale IP of the MBP).
- Has `/chat`, `/stt`, `/ocr`, `/hermes`, `/tools`, `/contextual_brief`,
  `/health`, `/debug`.
- TTS = **Kokoro** (python3.12 venv `~/venvs/jeeves-voice`).

> NOTE: There is a SEPARATE FastAPI server at `~/Public/Jeeves/voice/server.py`
> (launchd `com.jeeves.voice`, currently `.disabled`/not loaded). That one is
> the WS-based voice UI server, NOT what the Flutter app talks to. Do not add
> GA-V9 endpoints there expecting the iPad to use them. (Proactive brief code
> was briefly added there by mistake and reverted 2026-07-26.)

## Services (all verified live 2026-07-26)

| Capability | Endpoint | Backing | Status |
|---|---|---|---|
| Voice (TTS) | `/chat` | Kokoro (jeeves-voice venv) | ✅ `tts_ready: true` |
| LLM | `/chat`, `/contextual_brief` | Ollama `:11434` + MBP llamacpp `:8081` | ✅ both reachable |
| Elder-brain memory | `/hermes`, `/tools` | `~/elder-brain` vault | ✅ 1019 files indexed |
| Proactive car brief | `/contextual_brief` | seeded `ga_context.json` + LLM + Kokoro | ✅ audio + nav link |
| OCR | `/ocr` | EasyOCR/pytesseract | ✅ handler present |
| Weekly-training log | (written by `/chat`) | `~/Public/GA-V9/conversations.jsonl` | ✅ 301 lines, live |
| Intent training log | (written by classifier) | `~/Public/GA-V9/intent_training_data.jsonl` | ✅ live |

## The PYTHONPATH TTS bug (root cause + fix)

**Symptom:** server boots, but `/health` shows `tts_ready: false` and the log
says `Importing the numpy C-extensions failed ... No module named
'numpy._core._multiarray_umath'`.

**Root cause:** The Hermes desktop app injects `PYTHONPATH` pointing into its
own agent venv (`~/.hermes/hermes-agent/venv/lib/python3.11/site-packages`) into
the environment of every child process. The GA-V9 server runs on **python3.12**,
so that leaked path makes numpy's C-extensions (built for 3.11) fail to import,
which takes Kokoro down. The server's *own* venv has a correct numpy 2.4.6.

This is NOT in your shell profile (`~/.zshrc` etc. have no PYTHONPATH line) —
it's the Hermes app's process environment, inherited by launchd and shells.

**Fix (already applied, durable):** `server_v9.py` now strips any
`/.hermes/hermes-agent` path from `PYTHONPATH` and `sys.path` at startup,
*BEFORE* any numpy/kokoro import. So a plain launch (manual, launchd, or reboot)
keeps TTS working without manual `env -u PYTHONPATH`. Verified: killed the
server and let launchd restart it — `tts_ready: true` on its own.

### UNDO / MODIFY the PYTHONPATH fix
- **Disable** the strip (debugging): launch with `GA_KEEP_PYTHONPATH=1` — the
  block becomes a no-op and the leaked path is left in place.
- **Widen/narrow** what gets stripped: edit `_PYTHONPATH_BLOCKLIST` in
  `server_v9.py` (tuple of path substrings matched against PYTHONPATH/sys.path).
- The strip only affects the server process; it does NOT edit your profile,
  the Hermes app, or any other process. No launchd/env change was needed.

## How to restart / recover

The server is launchd-supervised with `KeepAlive`, so it auto-restarts on crash
and at login. Normal ops:

```bash
# Status
launchctl list | grep geezeraid-v9
curl http://127.0.0.1:8765/health

# Stop (launchd will NOT restart while loaded — it only restarts on crash)
launchctl unload ~/Library/LaunchAgents/com.geezeraid.server-v9.plist

# Start / reload
launchctl load   ~/Library/LaunchAgents/com.geezeraid.server-v9.plist

# Manual run (for debugging) — venv MUST be the jeeves-voice one:
source ~/.venvs/jeeves-voice/bin/activate
cd ~/Public/GA-V9 && python server_v9.py
```

Logs: `~/Library/Logs/GeezerAid/v9-server.log` (and `-error.log`).

> WARNING: `pkill -f server_v9.py` triggers an immediate launchd restart
> (KeepAlive), so you'll briefly see 2 instances; the supervised one owns 8765.
> Kill + wait a couple seconds for launchd to settle before testing. Manual
> `nohup python server_v9.py &` launches are ORPHANS — prefer launchctl.

## Editing endpoints (contract)

The Flutter app expects the response envelope from `/chat`:
`{text, audio (base64 wav), intent, tier, latency_ms}`. `/contextual_brief`
returns `{text, audio, actions:[{type:"nav_deeplink",url,label,provider}],
context, tools_called, latency_ms}`.

Always `py_compile` before restarting (see memory rule). Add new POST routes to
the `do_POST` allowlist in `ChatHandler`.

## Incident 2026-07-26: "Too many open files" (server stops responding)
Symptom: app shows `Connection reset by peer` to `100.85.123.9:8765`; server
process is alive (launchd loaded, `*:8765` LISTEN) but `curl` to 127.0.0.1 AND
the Tailscale IP both get no response. Server log shows
`[Errno 24] Too many open files` repeatedly.
Root cause: soft FD limit was 256 (launchctl `maxfiles 256 unlimited`). A client
retry storm (iPad hammered `/chat` 6+ times on a transient wedged connection)
exhausted sockets; server could no longer accept/open — accept() resets.
Fix applied: raised FD limit in the plist:
```
<key>SoftResourceLimits</key><dict><key>NumberOfFiles</key><integer>4096</integer></dict>
<key>HardResourceLimits</key><dict><key>NumberOfFiles</key><integer>8192</integer></dict>
```
UNDO: remove those two dicts from the plist, unload/load.
Recovery: `launchctl unload/load` the plist (fresh process starts with clean FDs
and the higher limit). A plain restart also clears the exhausted state.
Client-side hardening (optional, not yet done): add retry backoff in
`sendToServer`/`contextualBrief` so a wedged server doesn't get hammered 6x fast.

- [x] `/contextual_brief` in GA-V9 server_v9.py (supervised, live)
- [x] Editable `ga_context.json` (calendar/todos/directions/nav)
- [x] Flutter `car` beacon -> `/contextual_brief` + nav chip
- [x] PYTHONPATH TTS fix (durable, self-healing)
- [ ] Live Google Calendar + Directions (swap stub tools)
- [ ] GPS source decision (iPhone / cellular iPad)
- [ ] HERE/TomTom incidents for literal "wreck on 49" phrasing
