# GeezerAid V10 — Business Unit Coordination

## BU Structure

| BU | Role | Runs on | Responsibility |
|---|---|---|---|
| **BU-Brain** | Main AI | Strix | LLM, STT, TTS, memory, skills |
| **BU-Display** | TV Interface | Each TV | Ambient display, voice I/O |
| **BU-Mobile** | Phone | iPhone/Android | Voice, notifications, control |
| **BU-Home** | Smart Home | Strix + HA | Device control, automations |
| **BU-Vault** | Knowledge | Strix + Sync | Elder-brain, recipes, notes |

## Coordination via Event Bus

All BUs communicate via the event bus — no direct calls:

```
BU-Display publishes "ga.wake.detected"
  → BU-Brain subscribes, starts session
  → BU-Brain publishes "ga.response.ready"
  → BU-Display subscribes, shows response
  → BU-Home subscribes, executes actions
```

## Kanban Board: `ga-dev`

All development tracked via Hermes Kanban:
```bash
hermes kanban ls
hermes kanban create "title" --assignee default --body "description"
hermes kanban complete <id> --summary "done"
```

## Profiles (Hermes Bot Mode)

| Profile | BU | Model | Purpose |
|---|---|---|---|
| `default` | BU-Brain | LongCat (cloud) | Main development |
| `jeeves` | BU-Brain | Jeeves persona | Voice interface |
| `gtv` | BU-Display | — | TV-specific tasks |

## Sync Strategy

- **Vault**: Syncthing (folder `nd7chum3r96c`)
- **State**: CRDT sync engine (ga_modules/core/sync_engine.py)
- **Code**: GitHub (this repo)
- **Config**: `~/.hermes/config.yaml` per device
