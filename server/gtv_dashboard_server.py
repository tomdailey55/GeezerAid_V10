#!/usr/bin/env python3
"""GTV Dashboard server — serves the Chrome-hosted dashboard and its data API.

Runs on Strix. Two jobs:
  1. Serve the dashboard static files (dashboard.html + assets)
  2. Provide a small JSON API the dashboard's sheets consume:
       GET /api/recipe?q=cherries+jubilee   -> parsed recipe + source video
       GET /api/health

Reuses the elder-brain inverted index (recipe_index.json, 508 recipes)
so lookups stay in the <10ms class rather than scanning the vault.
"""
import json, re, os, queue, threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path

PORT = int(os.getenv("GTV_DASH_PORT", "8770"))
VAULT = Path(os.getenv("ELDER_BRAIN", str(Path.home() / "elder-brain")))
WEBROOT = Path(__file__).parent / "dashboard"

_index = None

# Connected dashboard clients (SSE). Each is a Queue of JSON-serializable cmds.
_clients = []
_clients_lock = threading.Lock()


def broadcast(cmd: dict):
    """Push a command to every connected dashboard."""
    with _clients_lock:
        dead = []
        for q in _clients:
            try:
                q.put_nowait(cmd)
            except Exception:
                dead.append(q)
        for q in dead:
            _clients.remove(q)


def load_index():
    """Load the elder-brain inverted index, building it if absent.

    The MBP has a prebuilt recipe_index.json. Strix has the synced vault but
    no index, so we build one from recipe filenames + frontmatter names — fast
    enough (a few hundred ms) and cached for the process lifetime.
    """
    global _index
    if _index is not None:
        return _index

    p = VAULT / "recipe_index.json"
    if p.exists():
        _index = json.loads(p.read_text())
        return _index

    # Fallback: build from the recipes directory.
    idx = {}
    rdir = VAULT / "recipes"
    if rdir.is_dir():
        for fp in rdir.glob("*.md"):
            rel = f"recipes/{fp.name}"
            # Index the slug words plus the frontmatter name, which together
            # cover the way people actually ask ("cherries jubilee").
            words = set(re.findall(r"[a-z]+", fp.stem.lower()))
            try:
                head = fp.read_text()[:400]
                m = re.search(r'^name:\s*"?([^"\n]+)"?', head, re.M)
                if m:
                    words |= set(re.findall(r"[a-z]+", m.group(1).lower()))
            except OSError:
                pass
            for w in words:
                if len(w) > 2:
                    idx.setdefault(w, []).append(rel)
    _index = idx
    return _index


def search_recipes(query: str, limit: int = 5):
    """Rank recipes for a spoken query.

    Scoring rewards (a) matching more of the query's words and (b) matching in
    the filename/title rather than merely somewhere in the body. Without the
    title weighting, a long recipe that happens to mention "beef" and
    "wellington" in passing outranks the actual Beef Wellington.
    """
    idx = load_index()
    words = [w for w in re.findall(r"[a-z]+", query.lower()) if len(w) > 2]
    if not words:
        return []

    scores = {}
    for w in words:
        for path in idx.get(w, []):
            scores[path] = scores.get(path, 0) + 1

    def rank(item):
        path, n_words = item
        stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
        # How many query words appear in the filename itself?
        in_title = sum(1 for w in words if w in stem)
        # Full phrase present in the slug is the strongest signal.
        phrase = 1 if "-".join(words) in stem else 0
        return (-(phrase * 10 + in_title * 3 + n_words), len(stem))

    return [p for p, _ in sorted(scores.items(), key=rank)[:limit]]


def parse_recipe(rel_path: str) -> dict:
    """Parse a recipe markdown file into structured JSON for the sheet."""
    fp = VAULT / rel_path
    if not fp.exists():
        return {}
    text = fp.read_text()

    # YAML frontmatter (simple key: "value" pairs)
    meta = {}
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end > 0:
            for line in text[3:end].splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip().strip('"')
            text = text[end + 4:]

    # Split on "## Section" headings
    sections, current = {}, None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip().lower()
            sections[current] = []
        elif current:
            sections[current].append(line)

    def items(name):
        out = []
        for ln in sections.get(name, []):
            s = ln.strip()
            if s.startswith(("- ", "* ")):
                out.append(s[2:].strip())
            elif re.match(r"^\d+\.\s", s):
                out.append(re.sub(r"^\d+\.\s*", "", s))
        return out

    # Extractor versions disagree on the frontmatter key for the source video:
    # older recipes use `source:`, newer ones `source_url:`. Accept either, plus
    # a couple of near-misses, so a tile never comes up empty when the URL is
    # right there in the file.
    src = ""
    for key in ("source", "source_url", "url", "video_url", "youtube"):
        val = meta.get(key, "").strip()
        if val:
            src = val
            break
    # Last resort: a bare YouTube link anywhere in the body (e.g. "## Source").
    if not src:
        m = re.search(r"https?://(?:www\.)?(?:youtube\.com/watch\?\S*|youtu\.be/\S+)", text)
        if m:
            src = m.group(0).rstrip(").,")

    return {
        "path": rel_path,
        "name": meta.get("name", fp.stem.replace("-", " ").title()),
        "servings": meta.get("servings", ""),
        "prep_time": meta.get("prep_time", ""),
        "cook_time": meta.get("cook_time", ""),
        "source": src,
        "source_title": meta.get("source_title", ""),
        "ingredients": items("ingredients"),
        "instructions": items("instructions"),
        "notes": items("notes"),
    }


def youtube_id(url: str) -> str:
    m = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{6,})", url or "")
    return m.group(1) if m else ""


_embed_cache = {}


def check_embeddable(video_id: str) -> bool:
    """True if YouTube will serve this video in an embed.

    Uses the oEmbed endpoint: 404 means removed/private, 401 means embedding
    disabled. Cached per process — a dead video stays dead.
    """
    import urllib.request, urllib.error
    if not video_id:
        return False
    if video_id in _embed_cache:
        return _embed_cache[video_id]
    url = ("https://www.youtube.com/oembed?url="
           f"https://www.youtube.com/watch?v={video_id}&format=json")
    try:
        urllib.request.urlopen(url, timeout=6)
        ok = True
    except urllib.error.HTTPError:
        ok = False          # 404 removed/private, 401 embedding disabled
    except Exception:
        ok = True           # network hiccup — don't punish the tile
    _embed_cache[video_id] = ok
    return ok


_frame_cache = {}


def check_frameable(url: str) -> bool:
    """True if a page can be shown in an iframe.

    Many sites (Rotten Tomatoes, Netflix, most streaming services) send
    X-Frame-Options or a restrictive CSP frame-ancestors, which makes an
    iframe render blank. Detecting it lets the dashboard fall back to a
    separate Chrome window instead of showing an empty tile.
    """
    import urllib.request
    if not url:
        return False
    if url in _frame_cache:
        return _frame_cache[url]
    ok = True
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            if r.headers.get("X-Frame-Options"):
                ok = False
            csp = r.headers.get("Content-Security-Policy", "")
            if "frame-ancestors" in csp:
                seg = next((p for p in csp.split(";") if "frame-ancestors" in p), "")
                if "*" not in seg:
                    ok = False
    except Exception:
        ok = True   # network hiccup — let the browser try
    _frame_cache[url] = ok
    return ok


# What is currently on the dashboard. Lets "play it" resolve without the user
# repeating the title, and lets Jeeves answer "what's on screen?".
_context = {"kind": None, "title": None, "url": None, "video_id": None}


def set_context(**kw):
    _context.update(kw)


# Streaming services, keyed by the words people actually say. Each entry is a
# search URL so "play it" lands on the title rather than the service home page.
STREAMING = {
    "netflix":     "https://www.netflix.com/search?q={q}",
    "hbo":         "https://play.max.com/search?q={q}",
    "max":         "https://play.max.com/search?q={q}",
    "prime":       "https://www.amazon.com/s?k={q}&i=instant-video",
    "amazon":      "https://www.amazon.com/s?k={q}&i=instant-video",
    "hulu":        "https://www.hulu.com/search?q={q}",
    "disney":      "https://www.disneyplus.com/search?q={q}",
    "paramount":   "https://www.paramountplus.com/search/{q}/",
    "peacock":     "https://www.peacocktv.com/search?q={q}",
    "apple":       "https://tv.apple.com/search?term={q}",
    "youtube":     "https://www.youtube.com/results?search_query={q}",
}


def streaming_url(service: str, query: str) -> str:
    import urllib.parse
    tmpl = STREAMING.get(service.lower())
    if not tmpl:
        return ""
    return tmpl.format(q=urllib.parse.quote(query))


def open_app_window(url: str, size: str = "1280,720", pos: str = "300,160"):
    """Open a URL in a positioned Chrome --app window on Strix.

    Used for pages that refuse iframing, and for DRM streaming services which
    cannot be composited into a tile but play fine in their own window (Chrome
    ships Widevine). Geometry MUST be set at launch: under GNOME Wayland,
    wmctrl/xdotool cannot reposition windows afterwards.

    IMPORTANT — the profile is PERSISTENT and deliberately separate from the
    kiosk dashboard's:
      * separate, because Chrome silently refuses a second window against a
        --user-data-dir already held by a running instance;
      * persistent, because streaming services require sign-in and those
        cookies must survive. NEVER delete this profile or pkill these windows
        as "cleanup" — the user loses every login.
    """
    import subprocess
    env = dict(os.environ)
    env["XDG_RUNTIME_DIR"] = f"/run/user/{os.getuid()}"
    env["WAYLAND_DISPLAY"] = env.get("WAYLAND_DISPLAY", "wayland-0")
    env.pop("DISPLAY", None)
    profile = Path.home() / ".config/gtv-chrome-app"
    profile.mkdir(parents=True, exist_ok=True)
    cmd = [
        "google-chrome", "--ozone-platform=wayland",
        f"--user-data-dir={profile}",
        "--no-first-run", "--no-default-browser-check",
        "--autoplay-policy=no-user-gesture-required",
        # Keep the window alive if the user closes a tab mid-login, and let
        # password/cookie storage work headlessly (no keyring prompt).
        "--password-store=basic",
        f"--app={url}", f"--window-size={size}", f"--window-position={pos}",
    ]
    try:
        subprocess.Popen(cmd, env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[gtv-dash] app window opened: {url}")
        return True
    except Exception as e:
        print(f"[gtv-dash] app window failed: {e}")
        return False


def open_signin_window(service: str) -> bool:
    """Open a NORMAL Chrome window (tabs, address bar, back button) so the user
    can sign in to a streaming service once.

    --app windows have no navigation chrome, which makes multi-step logins
    (email → password → 2FA → "not on this device?") painful or impossible.
    Sign-in therefore gets a full browser window against the SAME persistent
    profile, so the cookies it earns are the ones --app windows will use.
    """
    import subprocess
    home = {
        "netflix": "https://www.netflix.com/login",
        "hbo": "https://play.max.com", "max": "https://play.max.com",
        "prime": "https://www.amazon.com/gp/video/storefront",
        "amazon": "https://www.amazon.com/gp/video/storefront",
        "hulu": "https://www.hulu.com/login",
        "disney": "https://www.disneyplus.com/login",
        "paramount": "https://www.paramountplus.com/account/signin/",
        "peacock": "https://www.peacocktv.com/signin",
        "apple": "https://tv.apple.com",
        "youtube": "https://www.youtube.com",
    }.get(service.lower())
    if not home:
        return False
    env = dict(os.environ)
    env["XDG_RUNTIME_DIR"] = f"/run/user/{os.getuid()}"
    env["WAYLAND_DISPLAY"] = env.get("WAYLAND_DISPLAY", "wayland-0")
    env.pop("DISPLAY", None)
    profile = Path.home() / ".config/gtv-chrome-app"
    profile.mkdir(parents=True, exist_ok=True)
    cmd = [
        "google-chrome", "--ozone-platform=wayland",
        f"--user-data-dir={profile}",
        "--no-first-run", "--no-default-browser-check",
        "--password-store=basic",
        "--new-window", "--window-size=1400,900", "--window-position=200,80",
        home,
    ]
    try:
        subprocess.Popen(cmd, env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"[gtv-dash] sign-in window opened: {service}")
        return True
    except Exception as e:
        print(f"[gtv-dash] sign-in window failed: {e}")
        return False


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(WEBROOT), **kw)

    def log_message(self, format, *args):
        pass  # keep the journal quiet

    def _json(self, status, obj):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/health":
            idx = load_index()
            with _clients_lock:
                n = len(_clients)
            return self._json(200, {"ok": True, "index_words": len(idx),
                                    "dashboards": n})
        if u.path == "/api/recipe":
            q = (parse_qs(u.query).get("q") or [""])[0]
            hits = search_recipes(q)
            if not hits:
                return self._json(404, {"error": "no recipe found", "query": q})
            r = parse_recipe(hits[0])
            r["video_id"] = youtube_id(r.get("source", ""))
            r["alternates"] = hits[1:4]
            return self._json(200, r)
        if u.path == "/api/embeddable":
            v = (parse_qs(u.query).get("v") or [""])[0]
            return self._json(200, {"ok": check_embeddable(v), "video_id": v})
        if u.path == "/api/context":
            return self._json(200, dict(_context))
        if u.path == "/api/events":
            return self._sse()
        return super().do_GET()

    def _sse(self):
        """Server-Sent Events stream: relays Jeeves' commands to the dashboard."""
        q = queue.Queue(maxsize=64)
        with _clients_lock:
            _clients.append(q)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            while True:
                try:
                    cmd = q.get(timeout=20)
                    payload = json.dumps(cmd)
                    self.wfile.write(f"data: {payload}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")  # hold the connection
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            with _clients_lock:
                if q in _clients:
                    _clients.remove(q)

    def do_POST(self):
        """POST /api/command — Jeeves drives the dashboard.

        {"type":"recipe","q":"cherries jubilee","said":"..."}   -> look up + show
        {"type":"web","url":"...","title":"Reviews"}            -> live web tile
        {"type":"info","heading":"...","text":"..."}            -> context tile
        {"type":"step","n":5}                                   -> highlight step
        {"type":"idle"}                                         -> resting state
        """
        u = urlparse(self.path)
        if u.path != "/api/command":
            return self._json(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            cmd = json.loads(self.rfile.read(n).decode()) if n else {}
        except (ValueError, json.JSONDecodeError):
            return self._json(400, {"error": "invalid json"})

        # A recipe command resolves the vault lookup server-side, so the
        # dashboard receives fully-formed data rather than doing its own search.
        if cmd.get("type") == "recipe" and not cmd.get("data"):
            hits = search_recipes(cmd.get("q", ""))
            if not hits:
                return self._json(404, {"error": "no recipe found",
                                        "query": cmd.get("q", "")})
            r = parse_recipe(hits[0])
            r["video_id"] = youtube_id(r.get("source", ""))
            cmd["data"] = r

        # A web command is checked for frameability. Sites that refuse iframing
        # (Rotten Tomatoes, streaming services) get opened as a positioned
        # Chrome window instead of rendering as a blank tile.
        if cmd.get("type") == "web":
            data = cmd.setdefault("data", {})
            # Single URL may arrive at the top level; normalise into data.
            if not data.get("url") and cmd.get("url"):
                data["url"] = cmd["url"]
            targets = data.get("tiles") or ([data] if data.get("url") else [])
            for t in targets:
                url = t.get("url", "")
                if not url:
                    continue
                t["frameable"] = check_frameable(url)
                if not t["frameable"]:
                    open_app_window(url)
                    t["opened_window"] = True

        # ── sign in to a streaming service (one time, full browser window) ──
        if cmd.get("type") == "signin":
            service = cmd.get("service", "")
            if not open_signin_window(service):
                return self._json(404, {"error": f"unknown service: {service}",
                                        "known": sorted(STREAMING)})
            broadcast({"type": "info", "said": cmd.get("said", ""),
                       "data": {"title": "Sign in",
                                "heading": f"{service.title()} sign-in",
                                "meta": "full browser window — takes your time",
                                "text": "Sign in with the mouse and keyboard. "
                                        "The login is **remembered**, so this is "
                                        "a one-time step per service. Nothing "
                                        "will close the window automatically."}})
            return self._json(200, {"ok": True, "signin": service})

        # ── play: open a streaming service in its own window ──────────────
        # DRM (Widevine) cannot be composited into a tile, but Chrome plays it
        # fine in a resizable window with mouse/keyboard control. "play it"
        # resolves the title from whatever is currently on the dashboard.
        if cmd.get("type") == "play":
            title = cmd.get("title") or _context.get("title") or ""
            service = cmd.get("service", "netflix")
            if not title:
                return self._json(400, {"error": "nothing on screen to play",
                                        "hint": "show something first"})
            url = streaming_url(service, title)
            if not url:
                return self._json(404, {"error": f"unknown service: {service}",
                                        "known": sorted(STREAMING)})
            fullscreen = bool(cmd.get("fullscreen"))
            if fullscreen:
                open_app_window(url, size="1920,1080", pos="0,0")
            else:
                open_app_window(url)
            broadcast({"type": "info", "said": cmd.get("said", ""),
                       "data": {"title": "Playing",
                                "heading": title,
                                "meta": f"{service.title()} — own window",
                                "text": "Mouse and keyboard control the player. "
                                        "Say **back to the room** when you're done."}})
            with _clients_lock:
                n_clients = len(_clients)
            return self._json(200, {"ok": True, "played": title,
                                    "service": service, "url": url,
                                    "delivered_to": n_clients})

        # Remember what's on screen so "play it" needs no repetition.
        if cmd.get("type") == "recipe":
            d = cmd.get("data") or {}
            set_context(kind="recipe", title=d.get("name"),
                        video_id=d.get("video_id"), url=d.get("source"))
        elif cmd.get("type") == "web":
            d = cmd.get("data") or {}
            first = (d.get("tiles") or [d])[0] if (d.get("tiles") or d.get("url")) else {}
            set_context(kind="web", title=cmd.get("subject") or first.get("title"),
                        url=first.get("url"), video_id=None)
        elif cmd.get("type") == "idle":
            set_context(kind=None, title=None, url=None, video_id=None)

        broadcast(cmd)
        with _clients_lock:
            n_clients = len(_clients)
        return self._json(200, {"ok": True, "delivered_to": n_clients,
                                "type": cmd.get("type")})


if __name__ == "__main__":
    WEBROOT.mkdir(parents=True, exist_ok=True)
    print(f"[gtv-dash] serving {WEBROOT} on :{PORT} (vault={VAULT})")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
