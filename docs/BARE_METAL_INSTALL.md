# GeezerAid Strix — Bare-Metal Install & Survivability (BARE_METAL_INSTALL.md)

Canonical beta box: Strix (Fedora 44, x86_64, btrfs root+home on NVMe).
Last verified: 2026-07-10 (post twin power-cut health check — all clean).

This file is Part 1 of the belt-and-suspenders plan. Part 2 (rolling
snapshot + auto-backup + monitoring) is in SURVIVABILITY.md in this dir.

=====================================================================
PART 1 — FROM ZERO TO PRODUCTION AFTER A BARE-METAL WIPE
=====================================================================

THREAT MODEL THIS DOC DEFENDS AGAINST
  - Unclean power loss (thunderstorms) — FS corruption / no boot
  - SSD failure — total local data loss
  - Bad config edit — need point-in-time rollback
  - Box won't POST / motherboard dead — need offsite restore
Defense layers: btrfs COW + scrub | local snapshots | offsite USB
rotation | syncthing cross-instance | bootable live USB rescue.

---------------------------------------------------------------------
0. WHAT YOU NEED BEFORE YOU START
---------------------------------------------------------------------
  - The Fedora-44 live USB (currently /dev/sda on this box — LABEL
    "Fedora-WS-Live-44", 58.6G). Boot from it; it is a real installer.
  - At least ONE GABU* backup stick (GABU1..GABU4) with a recent
    snapshots/ga_*目录. Verify with:
        ~/Public/GA-V9/scripts/bu_status.sh
  - The Strix auth + config (in ~/.hermes) are part of the backup set,
    so a GABU* stick restores them too.
  - Network: Tailscale + docker-ce-stable + copr repos (see step 2).

---------------------------------------------------------------------
1. BOOT THE LIVE USB + REINSTALL FEDORA
---------------------------------------------------------------------
  a. Boot from the Fedora-WS-Live-44 USB (UEFI: Removable Device / the
     CD/DVD entry, or pick the USB in boot menu).
  b. Choose "Install to Hard Drive" (anaconda).
  c. Disk layout — MATCH THIS EXACTLY so snapshots/restore line up:
        /dev/nvme0n1
          p1 600M   vfat   /boot/efi
          p2 2G     ext4   /boot
          p3 928G   btrfs  (subvolumes: root @ /, home @ /home)
     Use the btrfs preset; create subvolumes "root" (mount /) and
     "home" (mount /home). Enable compression zstd:1 (matches current).
  d. Set hostname "strix", user "tom" (same UID 1000 — IMPORTANT so
     file ownership on restored backups is correct).
  e. Finish install, reboot into the new system (remove USB).

---------------------------------------------------------------------
2. BASE PACKAGES + REPOS (captured 2026-07-10 — stable set)
---------------------------------------------------------------------
  # Enable the same repos the box had:
  sudo dnf install -y dnf-plugins-core
  sudo dnf config-manager --add-repo \
       https://download.docker.com/linux/fedora/docker-ce.repo
  # Tailscale + copr (PyCharm) and rpmfusion were present:
  sudo dnf install -y tailscale
  # (copr/PyCharm and rpmfusion are optional — skip if not needed)

  # Core add-on packages (the box's non-default install, captured):
  sudo dnf install -y $(cat ~/Public/GA-V9/docs/pkglist-core.txt)
  # pkglist-core.txt contains exactly:
  #   btrfs-progs cronie efibootmgr git ollama python3-pip
  #   rsync smartmontools syncthing
  # NOTE: docker-ce pulls docker-ce-cli + docker-compose-plugin via the
  # repo above; install separately if not pulled:
  sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

  # Verify ollama binary + models live on the restored /home (they do —
  # models are under ~/.ollama which the backup restores).

---------------------------------------------------------------------
3. ENABLE SERVICES (auto-restart on boot — the "suspenders")
---------------------------------------------------------------------
  # System-level (Restart=always via their units):
  sudo systemctl enable --now ollama.service
  sudo systemctl enable --now docker.service

  # User-level (syncthing — Restart=on-failure, already enabled):
  systemctl --user enable --now syncthing.service
  # If the user service does not autostart after reboot, ensure
  # "lingering" is on so it runs without an active login session:
  sudo loginctl enable-linger tom

  # Tailscale:
  sudo systemctl enable --now tailscaled

  # Verify all green:
  systemctl is-enabled ollama docker
  systemctl --user is-enabled syncthing

---------------------------------------------------------------------
4. RESTORE DATA FROM THE GABU* STICK (offsite belt)
---------------------------------------------------------------------
  # Plug the most recent GABU* stick; it auto-mounts under /run/media/tom.
  # The stick holds snapshots/ga_YYYYMMDD_HHMMSS/{GA-V9,elder-brain,.hermes}
  # Restore each into place (rsync preserves perms/ownership):
  SNAP=$(ls -d /run/media/tom/GABU*/snapshots/ga_* | sort | tail -1)
  rsync -a --delete "$SNAP/GA-V9/"        ~/Public/GA-V9/
  rsync -a --delete "$SNAP/elder-brain/"  ~/elder-brain/
  rsync -a --delete "$SNAP/.hermes/"      ~/.hermes/
  # Re-login / reboot to pick up restored ~/.hermes auth + config.

---------------------------------------------------------------------
5. POST-RESTORE SMOKE TEST (run before trusting the box)
---------------------------------------------------------------------
  curl -s -m5 http://localhost:11434/api/tags >/dev/null && echo "ollama OK"
  curl -s -m5 http://localhost:8384/rest/health && echo "syncthing OK"
  systemctl --user status syncthing --no-pager | head -3
  btrfs device stats /   # expect all zeros
  sudo btrfs scrub status /

=====================================================================
PART 2 — SEE SURVIVABILITY.md (local snapshots, auto-backup timer,
          monitoring, UPS guidance, gap closure)
=====================================================================
