#!/usr/bin/env python3
"""Probe accessibility: list elements and press one by platform identifier.

Uses pymobiledevice3's AccessibilityAudit service (AX) to enumerate on-screen
elements and PRESS one by its platform_identifier — no coordinate guessing.

Usage:
    python tools/ax_press.py list                    # list all on-screen elements
    python tools/ax_press.py press "<substring>"      # press element whose
                                                       # caption/spoken_description
                                                       # contains substring
"""
import asyncio
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / ".venv-iphone-spike" / "lib" / "python3.12" / "site-packages"))
sys.path.insert(0, str(REPO / ".venv-iphone-spike" / "lib" / "python3.12" / "site-packages" / "pymobiledevice3"))

from pymobiledevice3.lockdown import create_using_usbmux  # noqa: E402
from pymobiledevice3.services.accessibilityaudit import AccessibilityAudit  # noqa: E402


async def _run(mode, needle):
    lockdown = await create_using_usbmux()
    async with AccessibilityAudit(lockdown) as service:
        elements = []
        async for element in service.iter_elements():
            elements.append(element)
        if mode == "list":
            for el in elements:
                d = el.to_dict()
                print(f"{d.get('caption','')[:45]:45} | {d.get('platform_identifier','')[:26]}")
            print(f"\n{len(elements)} elements")
            return
        # press mode
        needle_l = needle.lower()
        for el in elements:
            d = el.to_dict()
            caption = (d.get("caption") or d.get("spoken_description") or "").lower()
            if needle_l in caption:
                pid = d.get("platform_identifier")
                print(f"pressing {d.get('caption','')[:45]!r} pid={pid}")
                element_bytes = bytes.fromhex(pid)
                await service.perform_press(element_bytes)
                print("pressed")
                return
        print(f"no element matched {needle!r}")
        for el in elements:
            print(f"  - {el.to_dict().get('caption','')[:45]}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    mode = sys.argv[1]
    needle = sys.argv[2] if len(sys.argv) > 2 else ""
    asyncio.run(_run(mode, needle))
    return 0


if __name__ == "__main__":
    sys.exit(main())
