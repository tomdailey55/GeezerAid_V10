#!/usr/bin/env python3
"""WDA element tree WITH frames — from get_source XML hierarchy.
Gives name + label + exact x/y/w/h + type for every element."""
import asyncio, sys, json, re
sys.path.insert(0, ".")

async def main():
    from pymobiledevice3.remote.userspace_tunnel import establish_userspace_rsd
    from pymobiledevice3.services.wda import WdaServiceClient
    rsd = await establish_userspace_rsd(serial="00008103-000151462EC0801E", autopair=True)
    client = WdaServiceClient(service_provider=rsd, port=8100, timeout=20)
    sid = await client.start_session()
    src = await client.get_source(sid)
    # Parse XML elements: type name label x y width height
    elems = []
    # WDA source XML lines look like:
    # <XCUIElementTypeButton name="Settings" label="Settings" ... x="992" y="162" width="32" height="84" .../>
    tag_re = re.compile(r'<(\w+)\s+([^>]*?)/>')
    for m in tag_re.finditer(src):
        attrs = m.group(2)
        def g(key):
            mm = re.search(rf'\b{key}="([^"]*)"', attrs)
            return mm.group(1) if mm else None
        name = g('name') or g('label')
        x, y, w, h = g('x'), g('y'), g('width'), g('height')
        t = m.group(1).replace('XCUIElementType', '')
        # Only keep named elements (all types) — we want frames for anything named
        if name and x is not None:
            elems.append({"type": t, "name": name, "x": x, "y": y, "w": w, "h": h})
    # dedupe by name
    seen, out = set(), []
    for e in elems:
        if e["name"] not in seen:
            seen.add(e["name"]); out.append(e)
    print(json.dumps(out[:40], indent=1))

asyncio.run(main())
