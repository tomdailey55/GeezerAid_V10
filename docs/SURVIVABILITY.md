# Strix Survivability — Belt & Suspenders (SURVIVABILITY.md)

Companion to BARE_METAL_INSTALL.md. Written 2026-07-10 after twin
thunderstorm power-cuts that rebooted the box twice (18:08, 18:09).
The FS survived (btrfs COW, scrub clean, SMART PASSED) but the box had
NO automated backups running and NO local rollback layer. This closes
both gaps.

=====================================================================
THE 5 LAYERS (belt = primary, suspenders = redundancy)
=====================================================================
 L1  Filesystem integrity ...... btrfs COW + weekly scrub ........ [DONE]
 L2  Local point-in-time ....... btrfs snapshots of / & /home ..... [NEW]
 L3  Offsite rotation .......... GABU* USB sticks via bu_snapshot . [NEW timer]
 L4  Cross-instance ............ syncthing GA-V9 <-> MBP ......... [DONE]
 L5  Bootable rescue ............ Fedora-44 live USB + EFI entries  [DONE]
 +   Service auto-restart ...... ollama/docker/syncthing units .... [DONE]
 +   Health monitoring ......... health_check.sh + cron .......... [DONE]
 +   UPS ........................ HARDWARE — RECOMMENDED, see end . [ACTION]

=====================================================================
L2 — LOCAL SNAPSHOTS (rollback for bad edits / partial corruption)
=====================================================================
Script: ~/Public/GA-V9/scripts/ga_snapshot.sh
Takes a read-only btrfs snapshot of root + home subvols into
/.snapshots and /home/.snapshots, prunes to RETAIN (default 14).
Requires root (btrfs subvolume snapshot needs CAP_SYS_ADMIN).

SAFEST way to grant just this script sudo without a password:
  sudo visudo -f /etc/sudoers.d/ga-snapshot
  # contents:
  tom ALL=(root) NOPASSWD: /home/tom/Public/GA-V9/scripts/ga_snapshot.sh
Then schedule it (see timer below). To restore from a snapshot:
  sudo btrfs subvolume snapshot /.snapshots/root_YYYYMMDD_HHMMSS /mnt/root-restore
  # then rsync the fixed files out, or boot live USB and roll the
  # subvolume over.

=====================================================================
L3 — OFFSITE USB ROTATION (bu_snapshot.sh) — WIRE IT TO A TIMER
=====================================================================
bu_snapshot.sh already exists and works (rsync --link-dest to a GABU*
stick, prunes to RETAIN=60). It was NEVER scheduled, so backups only
happened if run by hand. Fix: install the systemd user timer below so
it runs daily at 03:07 (off-peak, avoids the 22:00-07:00 quiet window
only applies to user alerts, not backups).

Files (create under ~/Public/GA-V9/scripts/):
  ga-backup.service  -> ExecStart=.../bu_snapshot.sh
  ga-backup.timer    -> OnCalendar=*-*-* 03:07:00; Persistent=true
Enable:
  systemctl --user daemon-reload
  systemctl --user enable --now ga-backup.timer
Verify: systemctl --user list-timers ga-backup.timer

Rotation scheme (liberal, per your 64GB sticks):
  - 4 sticks GABU1..GABU4, one plugged at a time or rotated weekly.
  - GA-V9 (147M) + elder-brain (61M) + .hermes (~few hundred M) dedup
    via --link-dest, so each snapshot costs only deltas. 64GB holds
    HUNDREDS of snapshots — RETAIN=60 per stick is conservative.
  - Label a stick "GABU1" (etc.) with: sudo fatlabel /dev/sdX GABU1
    (vfat) or mkfs.exfat + exfatlabel. bu_snapshot only triggers on a
    LABEL starting "GABU".

=====================================================================
L4 / L5 / SERVICE / MONITORING — already in place, verify after reboot
=====================================================================
  - syncthing user service: Restart=on-failure, enabled. If it should
    run with NO login session, enable lingering: sudo loginctl
    enable-linger tom  (do this on the fresh install too).
  - ollama.service: Restart=always. docker.service: enabled.
  - Live USB /dev/sda (Fedora-WS-Live-44) = bootable rescue belt.
  - EFI BootOrder has Fedora + Removable fallback, so even if the
    fedora shim entry dies, "UEFI:Removable Device" boots the ESP.
  - health_check.sh writes ~/backups/health/*.log — keep it; it is the
    canary. (Currently invoked via cron; see drift note below.)

=====================================================================
GAP: STALE CRONTAB POINTS AT GA-V7 / GA-V8
=====================================================================
The user crontab still references PRE-MIGRATION paths:
  */5 * * * * cd ~/Public/GA-V7 && bash context-dump.sh
  0 13 * * 6 python3 ~/Public/GA-V8/scripts/weekly_review.py
  */5 * * * * python3 ~/Public/GA-V8/scripts/health_monitor.py
These are dead (GA-V9 is canonical). Either repoint them at GA-V9 or
delete. Recommended: delete the GA-V7 context-dump + GA-V8 lines; keep
health monitoring but point it at the GA-V9 health_check.sh. Fix after
you confirm what MBP still depends on (MBP watches GA-V7 coord state).

=====================================================================
ACTION: UPS (the actual root cause of today's cuts)
=====================================================================
No software replaces a clean shutdown. Get a SMALL line-interactive UPS
(APC Back-UPS 600VA / CyberPower 685VA ~$70) for the Strix box + modem.
Optionally add graceful auto-shutdown on battery:
  - apcupsd (USB HID UPS) -> `sudo dnf install apcupsd`, set
    BATTERYLEVEL 15 / TIMEOUT 120 in /etc/apcupsd/apcupsd.conf,
    systemctl enable --now apcupsd. It signals shutdown before the
    battery dies, so btrfs always gets a clean unmount.
This is the single highest-value survivability upgrade.

=====================================================================
ONE-COMMAND HEALTH CHECK (run after any power event)
=====================================================================
  ~/Public/GA-V9/scripts/health_check.sh      # writes ~/backups/health/
  btrfs device stats /                         # all zeros = clean
  sudo btrfs scrub status /
  systemctl --user status syncthing --no-pager | head -3
  curl -s -m5 http://localhost:11434/api/tags >/dev/null && echo ollama-OK
