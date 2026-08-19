# GeezerAid V10

Modular AI household system. Voice-first, local-first, self-contained.

## Architecture

```
GeezerAid_V10/
├── ga_modules/          # Core module framework
│   ├── core/            # Event bus, state, coordinator, HA bridge, sync, discovery
│   ├── modules/         # Perceive, cognize, action, knowledge
│   └── tests/           # 112 tests
├── server/              # Strix-side servers (voice, dashboard, WS)
├── dashboard/           # Genius TV Chrome dashboard
├── docs/                # Architecture, skills, mockups
└── scripts/             # Deployment & control scripts
```

## Quick Start

```bash
# Install
python3.13 -m venv .venv && source .venv/bin/activate
pip install -e ga_modules/

# Test
python3 -m pytest ga_modules/tests/ -v

# Run
python3 -c "from ga_modules.core.system import GeezerAid; ga = GeezerAid('gtv-kitchen'); ga.start()"
```

## Modules

| Module | What | Interface |
|---|---|---|
| Perceive | STT + wake word | `transcribe()`, `detect_wake_word()` |
| Cognize | LLM routing | `generate()`, `select_tool()` |
| Action | TTS + display | `speak()`, `show_text()`, `play_audio()` |
| Knowledge | Vault search | `answer()`, `search_recipes()` |

## Routing

1. Safety check → 2. HA intents → 3. Local knowledge → 4. HA tools → 5. Local LLM → 6. Cloud LLM

## License

MIT
