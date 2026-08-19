---
name: ga-v8-modular
description: "Drive GeezerAid's modular AI household system — event bus, state, coordinator, HA bridge, and edge modules."
version: 0.1.0
author: Tom Dailey, Hermes Agent
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [ga, geezeradid, smart-home, multi-device, household]
    related_skills: [gtv-chrome-dashboard, syncthing-troubleshooting]
---

# GeezerAid V8 — Modular Household AI

The modular rewrite of GeezerAid. Every capability is a module with a
stable interface; modules communicate via an event bus. Modules can be
redistributed across devices as hardware changes.

## Architecture

```
GeezerAid (ga_modules/)
├── core/
│   ├── __init__.py          # Event bus (pub/sub, MQTT wildcards)
│   ├── state_manager.py     # Session + device + household state
│   ├── coordinator.py       # Routing policy (safety → HA → LLM)
│   ├── ha_bridge.py         # Home Assistant integration + safety
│   ├── sync_engine.py       # CRDT state sync
│   ├── discovery.py         # mDNS device discovery
│   └── system.py            # Main wiring
├── modules/
│   ├── perceive.py          # STT (whisper.cpp) + wake word
│   ├── cognize.py           # LLM routing (local + cloud)
│   ├── action.py            # TTS (Kokoro) + display control
│   └── knowledge.py         # Vault search (recipes, notes)
└── tests/                   # 112 tests
```

## Module Interfaces

| Module | Interface | Key Methods |
|---|---|---|
| Perceive | audio → text | `transcribe()`, `detect_wake_word()`, `extract_command()` |
| Cognize | prompt → response | `generate()`, `select_tool()` |
| Action | command → output | `speak()`, `show_text()`, `show_image()`, `play_audio()` |
| Knowledge | query → answer | `answer()`, `search_recipes()`, `search_notes()` |

## Routing Policy (Coordinator)

1. **Safety check** — block dangerous actions (server power, water heater)
2. **HA built-in intents** — "turn on lights" → 200ms, no LLM
3. **GA local knowledge** — recipes, calendar, preferences
4. **HA tool calling** — device control via LLM
5. **Local LLM** — llama.cpp on Strix (Qwen3.5-9B)
6. **Cloud LLM backup** — Nous API (LongCat)

## Event Bus Topics

| Topic | When | Payload |
|---|---|---|
| `ga.wake.detected` | Wake word heard | `{device_id, user}` |
| `ga.command.received` | Command transcribed | `{device_id, text, context}` |
| `ga.intent.matched` | HA intent matched | `{device_id, intent, entity}` |
| `ga.response.ready` | LLM response ready | `{device_id, text, source}` |
| `ga.display.update` | Update display | `{device_id, target, content}` |
| `ga.device.state` | Device state change | `{entity_id, service, result}` |
| `ga.household.change` | Shared state change | `{key, value}` |

## Safety Rules (default)

- NEVER turn off server power
- NEVER turn off water heater
- NEVER turn off network security
- "Turn off the office" → only lights, not switches

## Sync Engine

CRDT-based state sync between devices:
- Last-Writer-Wins (LWW) per key
- Vector clocks track causality
- Operation log for replay/sync
- Works offline, merges on reconnect

## Running Tests

```bash
cd ~/Public/GA-V9
source .venv_ga/bin/activate
python3 -m pytest ga_modules/tests/ -v
```

## Deploying to Strix

1. Copy ga_modules: `scp -r ga_modules tomdailey@100.103.195.22:~/mbp-public/GA-V9/`
2. Install: `cd ~/Public/GA-V9 && python3.13 -m venv .venv && pip install -e .`
3. Import: `from ga_modules.core.system import GeezerAid`

## Pitfalls

- **Event bus singleton** — one bus per process. Tests use fresh instances.
- **Household state** — without sync engine, falls back to local dict.
- **HA bridge** — without HA URL, intent matching is unavailable.
- **Python version** — Hermes needs <3.14; Strix ships 3.14, so install 3.13 from deadsnakes PPA.
- **whisper.cpp** — perceive module needs whisper.cpp built on the target device.

## See Also

- `gtv-chrome-dashboard` — Genius TV Chrome dashboard
- `syncthing-troubleshooting` — vault sync between devices
