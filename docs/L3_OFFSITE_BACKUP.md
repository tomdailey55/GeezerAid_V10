# L3 Offsite Backup — GABU USB Stick (exFAT + tar)

## Status: WORKING (verified 2026-07-13)

## What it does
`scripts/bu_snapshot.sh` runs on a daily `ga-backup.timer` (03:07, user-level,
Persistent). When a USB stick whose LABEL starts with `GABU` is mounted, it
archives three sources into timestamped tarballs under `snapshots/ga_<stamp>/`:

- `~/Public/GA-V9`   -> GA-V9.tar
- `~/elder-brain`    -> elder-brain.tar
- `~/.hermes`        -> .hermes.tar  (DURABLE DATA ONLY — see below)

## Why tar (not rsync) on this stick
The GABU stick is **exFAT** — chosen because it is natively readable on
macOS, Linux, and Windows with no drivers, and has no 4GB file limit.

exFAT CANNOT store:
- symlinks  (rsync fails: "Operation not permitted")
- filenames with `? : * < > |`  (rsync fails: "Invalid argument")

So the script archives each source into a **tarball**. Tar preserves
symlinks / permissions / odd filenames INTERNALLY; the stick only holds the
`.tar` file (named by us, always legal). Mac can open these tars natively.

## ~/.hermes scope (IMPORTANT)
`~/.hermes` is ~4.6G of LIVE-CHANGING data (running agent venv, live
`state.db` written every second, caches, logs). Taring it live caused
"file changed as we read it" AND is mostly reinstallable app/cache.

The backup keeps ONLY durable user data and EXCLUDES:
- `hermes-agent` (the app install/venv — reinstallable)
- `state.db*`, `state-snapshots`, `state.db-wal/shm` (live DB churn)
- `checkpoints`, `sessions`, `logs`, `audio_cache`, `cache`, `lsp`,
  `bin`, `platforms`, `image_cache`, `images`, `sandboxes`
- `cron/` runtime tickers, `*.lock`, `gateway.pid`, `gateway_state.json`,
  `processes.json`
- `tar --warning=no-file-changed` is set as a safety net for any remaining
  harmless churn during the read.

Result: `.hermes.tar` ≈ 70M containing MEMORY.md, USER.md, skills/,
profiles/, iOS-app/, scripts/, config.yaml, kanban*, context-dumps.

## Restoring
On Mac or Linux:
```
# mount the stick, then:
mkdir -p ~/restore && tar -xf /Volumes/GABU01/snapshots/ga_<stamp>/GA-V9.tar -C ~/restore
```
Files extract with original structure + permissions (tar preserved them).

## Stick setup (for a replacement stick)
```
sudo exfatlabel /dev/sdX1 GABU01      # label MUST start with GABU
# mount it; the timer will pick it up next run (or run bu_snapshot.sh manually)
```
Label is the only detection key (not UUID/device/fs). exFAT is fine.

## Restore-from-power-loss note
This L3 layer complements:
- L1: Syncthing (macPublic <-> MBP, live)
- L2: btrfs read-only snapshots via ga-snapshot.timer (local, 03:02)
- L3: GABU USB offsite (this script) — protects against box loss / total failure

First successful L3 run: 2026-07-13, snapshot ga_20260713_112709 (276M total,
all 3 tars pass `tar -tf` integrity).
