/* Genius TV Dashboard — sheet renderer + command API.
 *
 * Jeeves drives this by POSTing commands to the server, which relays them
 * here over SSE (/api/events). Sheets are pure functions: state -> DOM.
 */

const tiles = document.getElementById("tiles");
const said = document.getElementById("said");
const dot = document.getElementById("dot");
const clock = document.getElementById("clock");

// ── clock ──────────────────────────────────────────────────
function tickClock() {
  clock.textContent = new Date().toLocaleTimeString([], {
    hour: "numeric", minute: "2-digit"
  });
}
tickClock();
setInterval(tickClock, 10000);

// ── helpers ────────────────────────────────────────────────
const esc = (s) => String(s ?? "").replace(/[&<>"]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// Markdown-lite: **bold** -> <b>
const md = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");

function layout(kind) {
  tiles.className = kind;
  tiles.innerHTML = "";
}

function addTile(title, badge, bodyHtml, opts = {}) {
  const el = document.createElement("div");
  el.className = "tile" + (opts.pad0 ? " pad0" : "");
  const head = title
    ? `<h3>${esc(title)}${badge ? `<span class="badge ${badge.kind || ""}">${esc(badge.text)}</span>` : ""}</h3>`
    : "";
  el.innerHTML = head + (opts.raw ? bodyHtml : `<div class="body">${bodyHtml}</div>`);
  tiles.appendChild(el);
  return el;
}

// ── sheets ─────────────────────────────────────────────────
const Sheets = {
  idle() {
    layout("one");
    addTile(null, null, `
      <div class="empty">
        <div class="big">Genius TV</div>
        <div class="hint">
          <span>“show me my recipe for cherries jubilee with the video”</span><br>
          <span>“show me reviews of Game of Thrones”</span><br>
          <span>“back to the room”</span>
        </div>
      </div>`, { raw: true });
  },

  // Recipe + its source video, side by side
  recipe(r) {
    layout("two");
    const ing = (r.ingredients || []).map((i) => `<li>${md(i)}</li>`).join("");
    const ins = (r.instructions || []).map((i) => `<li>${md(i)}</li>`).join("");
    const notes = (r.notes || []).map((n) => `<li>${md(n)}</li>`).join("");
    const metaBits = [
      r.servings && `Serves ${esc(r.servings)}`,
      r.prep_time && `prep ${esc(r.prep_time)}`,
      r.cook_time && `cook ${esc(r.cook_time)}`,
    ].filter(Boolean).join(" · ");

    addTile("Recipe", { text: "elder-brain", kind: "live" }, `
      <h2 class="title">${esc(r.name)}</h2>
      <div class="meta">${metaBits}</div>
      <div class="sec">Ingredients</div><ul>${ing}</ul>
      <div class="sec">Instructions</div><ol id="steps">${ins}</ol>
      ${notes ? `<div class="sec">Notes</div><ul>${notes}</ul>` : ""}
    `);

    if (r.video_id) {
      // Embeds can fail for reasons outside our control: the video was
      // removed/privatised since ingest, or the owner disabled embedding.
      // Offer a direct link so the tile is never a dead end.
      const watch = `https://www.youtube.com/watch?v=${esc(r.video_id)}`;
      // autoplay=1 + mute=1 is the only combination browsers honour without a
      // click. Chrome also runs with --autoplay-policy=no-user-gesture-required,
      // but the embed URL must still ASK to autoplay.
      const src = `https://www.youtube.com/embed/${esc(r.video_id)}`
        + `?rel=0&enablejsapi=1&autoplay=1&mute=1&playsinline=1`;
      const el = addTile("Source video", { text: "in-tile", kind: "live" }, `
        <div class="vwrap" id="vid">
          <div class="ar">
            <iframe allow="autoplay; encrypted-media; picture-in-picture"
              allowfullscreen src="${src}"></iframe>
          </div>
        </div>
        <div id="vfallback" style="display:none" class="empty">
          <div class="big">Video unavailable</div>
          <div class="hint">
            It was removed or embedding is disabled.<br>
            <span>${esc(r.source_title || watch)}</span><br>
            <span>say “open the video” to try it in a browser window</span>
          </div>
        </div>`);

      // Ask YouTube whether the video is embeddable; swap to the fallback if not.
      fetch(`/api/embeddable?v=${encodeURIComponent(r.video_id)}`)
        .then((res) => res.json())
        .then((d) => {
          if (!d.ok) {
            el.querySelector("#vid").style.display = "none";
            el.querySelector("#vfallback").style.display = "flex";
          }
        })
        .catch(() => {});
    } else {
      addTile("Source video", { text: "none", kind: "" },
        `<div class="empty"><div class="hint">No source video on this recipe.</div></div>`);
    }
  },

  // A live web page (reviews, anything non-DRM). Sites that refuse iframing
  // are opened in their own Chrome window by the server; the tile then says so
  // rather than showing a blank frame.
  web(o) {
    const tiles_ = Array.isArray(o.tiles) ? o.tiles : null;
    layout(tiles_ ? "two" : "one");

    const render = (t) => {
      if (t.frameable === false) {
        addTile(t.title || "Web", { text: "own window", kind: "adb" }, `
          <div class="empty">
            <div class="big">Opened in a window</div>
            <div class="hint">
              <span>${esc(t.url)}</span><br>
              This site blocks embedding, so it's in its own<br>
              resizable window — mouse and keyboard work there.
            </div>
          </div>`);
      } else {
        addTile(t.title || "Web", { text: "live web", kind: "live" },
          `<iframe src="${esc(t.url)}" referrerpolicy="no-referrer"></iframe>`,
          { pad0: true });
      }
    };

    if (tiles_) tiles_.forEach(render);
    else render(o);
  },

  // Arbitrary text/context tile (catch-up, cast list, plot summary)
  info(o) {
    layout("one");
    addTile(o.title || "Info", o.badge, `
      ${o.heading ? `<h2 class="title">${esc(o.heading)}</h2>` : ""}
      ${o.meta ? `<div class="meta">${esc(o.meta)}</div>` : ""}
      <div style="font-size:16px;line-height:1.9">${md(o.text || "")}</div>`);
  },
};

// ── highlight a recipe step ("back up to the flambé step") ──
function highlightStep(n) {
  document.querySelectorAll("#steps li").forEach((li, i) => {
    li.classList.toggle("on", i === n - 1);
  });
  const on = document.querySelector("#steps li.on");
  if (on) on.scrollIntoView({ block: "center", behavior: "smooth" });
}

// Find a step by a word spoken aloud ("the flambé step") and highlight it.
// Accent-insensitive, so "flambe" matches "flambé".
function highlightStepByWord(word) {
  const norm = (s) => s.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  const w = norm(word || "");
  if (!w) return;
  const steps = [...document.querySelectorAll("#steps li")];
  const i = steps.findIndex((li) => norm(li.textContent).includes(w));
  if (i >= 0) highlightStep(i + 1);
}

// Playback rate for any video in a tile ("slow that down").
// YouTube iframes are controlled through the postMessage API; plain <video>
// elements get playbackRate set directly.
function setRate(rate) {
  const r = Math.max(0.25, Math.min(2.0, Number(rate) || 1.0));
  document.querySelectorAll("video").forEach((v) => { v.playbackRate = r; });
  document.querySelectorAll("iframe").forEach((f) => {
    try {
      f.contentWindow.postMessage(JSON.stringify({
        event: "command", func: "setPlaybackRate", args: [r],
      }), "*");
    } catch (e) { /* cross-origin: nothing else we can do */ }
  });
  said.textContent = r === 1 ? "Normal speed." : `Playback at ${r}\u00d7.`;
}

// ── command dispatch ───────────────────────────────────────
function apply(cmd) {
  if (!cmd || !cmd.type) return;
  if (cmd.said) said.textContent = "\u201c" + cmd.said + "\u201d";

  switch (cmd.type) {
    case "recipe":     Sheets.recipe(cmd.data || {}); break;
    case "web":        Sheets.web(cmd.data || {}); break;
    case "info":       Sheets.info(cmd.data || {}); break;
    case "idle":       Sheets.idle(); break;
    case "step":       highlightStep(cmd.n); break;
    case "step_by_word": highlightStepByWord(cmd.word); break;
    case "rate":       setRate(cmd.rate); break;
    case "status":     dot.className = cmd.state || ""; break;
    case "say":        break; // transcript only
    default:           console.warn("unknown command", cmd);
  }
}

// ── live channel (SSE) with auto-reconnect ─────────────────
function connect() {
  const es = new EventSource("/api/events");
  es.onopen = () => { dot.className = ""; };
  es.onmessage = (e) => {
    try { apply(JSON.parse(e.data)); } catch (err) { console.error(err); }
  };
  es.onerror = () => {
    dot.className = "off";
    es.close();
    setTimeout(connect, 3000);
  };
}

Sheets.idle();
connect();

// Expose for manual testing from devtools
window.gtv = { apply, Sheets, highlightStep };
