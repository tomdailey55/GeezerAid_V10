#!/usr/bin/env python3
"""wda_direct.py — run a WDA subcommand over the NO-ROOT userspace tunnel.

Replaces the sudo-gated `--tunnel` CLI path so WDA control works without sudo.
Uses establish_userspace_rsd (no-root, iOS 17.4+ CoreDeviceProxy) + raw WdaServiceClient.

The target device is AUTO-DETECTED: if exactly one iOS device is on USB, use it;
else pass the UDID explicitly.

Usage: wda_direct.py [UDID] status|list|tap <sel>|open <app>|press <names>
  UDID — optional; if omitted, auto-detect the connected iOS device.
"""
import asyncio, sys, json, re

DEFAULT_UDID = "00008103-000151462EC0801E"  # iPad

async def _detect_udid():
    """Return the UDID of the single connected USB iOS device, else DEFAULT_UDID."""
    from pymobiledevice3.usbmux import list_devices
    try:
        devs = await list_devices()
        usb = [d.serial for d in devs if getattr(d, "is_usb", False) and d.serial]
        if len(usb) == 1:
            return usb[0]
        return DEFAULT_UDID
    except Exception:
        return DEFAULT_UDID


async def _client(udid):
    from pymobiledevice3.remote.userspace_tunnel import establish_userspace_rsd
    from pymobiledevice3.services.wda import WdaServiceClient
    rsd = await establish_userspace_rsd(serial=udid, autopair=True)
    return WdaServiceClient(service_provider=rsd, port=8100, timeout=20)


def _icon_rects(src):
    """Return list of (name, x, y) for visible Icon elements with real frames."""
    out = []
    for m in re.finditer(r'<XCUIElementTypeIcon([^>]*)/?>', src):
        tag = m.group(1)
        vis = re.search(r'visible="(\w+)"', tag)
        if vis and vis.group(1) != "true":
            continue
        name = re.search(r'name="([^"]*)"', tag)
        x = re.search(r'x="([\d.]+)"', tag)
        y = re.search(r'y="([\d.]+)"', tag)
        if name and x and y:
            out.append((name.group(1), float(x.group(1)), float(y.group(1))))
    return out


async def _coord_tap(client, sid, x, y):
    """Tap at absolute screen coordinates via WDA's wda/tap endpoint."""
    await client._request_json("POST", f"/session/{sid}/wda/tap", {"x": x, "y": y})


async def _main(op, args, udid):
    client = await _client(udid)

    if op == "status":
        try:
            s = await client.get_status()
            os = s.get("value", {}).get("os", {})
            print(f"WDA up, iOS {os.get('version')} ({udid})")
            return 0
        except Exception as e:
            print(f"WDA down: {e}", file=sys.stderr); return 1

    if op == "list":
        try:
            sid = await client.start_session()
            src = await client.get_source(sid)
            items = []
            for m in re.finditer(r'<(\w+)([^>]*?)/?>', src):
                attrs = m.group(2)
                def g(k):
                    mm = re.search(rf'\b{k}="([^"]*)"', attrs)
                    return mm.group(1) if mm else None
                name = g('name'); label = g('label')
                if name or label:
                    items.append({"name": name, "label": label,
                                  "type": m.group(1).replace('XCUIElementType','')})
            print(json.dumps(items))
            return 0
        except Exception as e:
            print(f"list error: {e}", file=sys.stderr); return 1

    if op == "tap":
        try:
            sid = await client.start_session()
            el = await client.find_element(args.using, args.selector, session_id=sid)
            await client.click(el, session_id=sid)
            print("tapped")
            return 0
        except Exception as e:
            print(f"tap error: {type(e).__name__}: {e}", file=sys.stderr)
            return 1 if "unable to find" in str(e) else 2

    if op == "open":
        # Robust app launcher: find a VISIBLE Icon by name via class-chain
        # predicate (excludes hidden widget elements). Press home first.
        app = args[0] if isinstance(args, list) else args
        try:
            sid = await client.start_session()
            await client.press_button('home', session_id=sid)
            await asyncio.sleep(1.0)
            # visible icon named exactly `app` — visible==1 excludes widget copies
            chain = f'**/XCUIElementTypeIcon[`label == "{app}" AND visible == 1`]'
            try:
                r = await client._request_json('POST', f'/session/{sid}/element',
                                               {'using': 'class chain', 'value': chain})
            except Exception as e:
                print(f"not on current page ({type(e).__name__}); swiping", file=sys.stderr)
                await client.swipe(300, 400, 80, 400, session_id=sid)
                await asyncio.sleep(1.0)
                r = await client._request_json('POST', f'/session/{sid}/element',
                                               {'using': 'class chain', 'value': chain})
            val = r.get('value', {})
            elid = val.get('ELEMENT') or val.get('element-6066-11e4-a52e-4f735466cecf')
            if elid:
                await client.click(elid, session_id=sid)
                print(f"opened {app}")
                return 0
            print(f"could not find visible icon '{app}'", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"open error: {type(e).__name__}: {e}", file=sys.stderr)
            return 1

    if op == "press":
        try:
            sid = await client.start_session()
            for name in args:
                await client.press_button(name, session_id=sid)
            print("pressed")
            return 0
        except Exception as e:
            print(f"press error: {e}", file=sys.stderr); return 1

    print(f"unknown op {op}", file=sys.stderr); return 1


if __name__ == "__main__":
    argv = sys.argv[1:]
    # Optional leading UDID
    udid = None
    if argv and ("-" in argv[0] and len(argv[0]) > 20):
        udid = argv[0]; argv = argv[1:]
    op = argv[0] if argv else "status"
    rest = argv[1:]
    from types import SimpleNamespace
    a = SimpleNamespace(using="name", selector=(rest[0] if rest else ""))
    if "--using" in rest:
        a.using = rest[rest.index("--using")+1]
        a.selector = rest[0]
    if udid is None:
        udid = asyncio.run(_detect_udid())
    sys.exit(asyncio.run(_main(op, a if op in ("tap","list") else rest, udid)))
