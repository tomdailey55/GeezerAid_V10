# GeezerAid V9 — Rotating USB Backup Plan (2026-07-10)

## Goal
Offsite, rotating backups of the canonical beta sources. 3-2-1 compliant:
- Copy 1: Strix live (`~/Public/GA-V9`, `~/elder-brain`)
- Copy 2: MBP via Syncthing (`geezeraid-v9`, `hermes-config`)
- Copy 3: rotating USB sticks, one kept OFFSITE (away from the machine)

## Sources backed up (each run)
- `~/Public/GA-V9`            (~147M; intent_v4 static 146M)
- `~/elder-brain`             (~61M)
- `~/.hermes`                 (config + auth + Nous creds + cron scripts; cheap insurance)
Total source ≈ **500M**.

NOT backed up (intentionally): GA-V7 (archive, 4.3G w/ 2.9G venv cruft), state.db (355M),
audio_cache, hermes-agent venv. Those are rebuildable / already on MBP.

## Hardware: 4× 64GB USB sticks
Label them: `GABU1` `GABU2` `GABU3` `GABU4`. (Use 3 if you prefer — just label GABU1-3;
script auto-detects any `GABU*` stick.)

### Filesystem choice (decide at format time)
- **btrfs** (recommended, Linux/Strix native): compression + hardlink dedup → each snapshot
  after the first costs ~2M/day. One stick holds YEARS of daily snapshots. Format on Strix:
  `mkfs.btrfs -L GABU1 /dev/sdX` (do per stick, one at a time).
- **exFAT** (if you want to read the stick on macOS too): works, but NO hardlink dedup →
  each snapshot is a full ~500M copy. Still fits ~120 snapshots on a 64GB stick. Fine.
- Avoid FAT32 (4GB file cap — safe today but fragile if models ever land here).

## Rotation scheme (generations)
- Keep **one stick mounted in/near the machine** (the "live" backup, updated by daily cron).
- Keep **one stick offsite** (home/office/safe — the disaster-recovery copy).
- Swap sticks on a cadence: **weekly** is plenty (4 sticks = ~4 weeks of independent points).
  Simpler: swap the live stick for the next in sequence each time you remember; the
  `bu_status.sh` helper tells you which stick was last used so you rotate through them.
- Each stick is self-contained: it holds its own rolling 60-snapshot history, so ANY single
  stick is a full recovery + point-in-time rollback. You do not need all 4 to restore.

## Retention (liberal)
- `RETAIN=60` snapshots per stick (≈60 days of daily history per stick, or more with dedup).
- 4 sticks × 60 snapshots ≈ 240 independent restore points total.
- Space math (btrfs, dedup): base 500M + 240×~2M churn ≈ **~1G across all sticks**.
  Even un-deduplicated (exFAT): 240×500M ≈ 120G — still fits 4×64G with room to spare.
  You will never run out of space. This is the "liberal" part.

## Restore procedure
1. Mount the chosen stick (`GABU1`..`GABU4`).
2. Pick a snapshot: `ls /run/media/tom/GABU2/snapshots/`
3. Copy back: `rsync -a /run/media/tom/GABU2/snapshots/ga_20260712_031000/GA-V9/ ~/Public/GA-V9/`
   (or just copy the specific file you need).
4. Each snapshot has a `MANIFEST.txt` (date, stick, sources, size) for verification.

## Verification
- `bu_snapshot.sh` writes `~/backups/last_run.log` (per run) and `~/backups/rotation.log`
  (which stick, when).
- After a swap, run `bu_status.sh` to confirm the stick mounted and a new snapshot appeared.
- Optional sanity: `rsync -n` dry-run or `diff -r` a key file vs live (not automated yet).

## Cadence
- Daily cron (guarded): runs only if a `GABU*` stick is mounted; otherwise exits 0 silently.
  So it's safe to leave the cron on — it just does nothing on days no stick is plugged in.
- You physically swap sticks on your own schedule (weekly suggested).

## Files
- `scripts/bu_snapshot.sh` — the worker (guarded, dedup, per-stick prune, manifest).
- `scripts/bu_status.sh`  — shows last-used stick + currently mounted stick.
- Cron `ga-usb-backup` — daily, guarded (no_agent).
