// Simulated TIDAL desktop app for end-to-end tests.
//
// * Serves the Chrome DevTools Protocol endpoints tidal-shuffle uses
//   (/json/version, /json, and a page websocket that runs Runtime.evaluate
//   inside a jsdom copy of the web player), rejecting websocket upgrades that
//   carry an Origin header exactly like Chromium does.
// * Simulates playback: a footer with title/artist/track link/clock, play
//   controls, SPA routing to /track/<id> pages whose rows start playback,
//   and auto-advance to an album track when a song ends.
// * Exposes test-only endpoints under /__ for the fake media-control,
//   osascript and open binaries and for the test itself.
//
// usage: node server.mjs <port> <catalog.json> <log file>

import http from "node:http";
import fs from "node:fs";
import { JSDOM } from "jsdom";
import { WebSocketServer } from "ws";

const port = Number(process.argv[2]);
const catalog = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const logFile = process.argv[4];
const log = (msg) => fs.appendFileSync(logFile, `${new Date().toISOString()} ${msg}\n`);

const byId = Object.fromEntries(catalog.tracks.map((t) => [t.id, t]));
const state = { current: null, playing: false, startedWall: 0, pausedPos: 0, played: [], opened: [] };

const dom = new JSDOM(
  `<!doctype html><html><head><title>TIDAL</title></head><body>
     <main id="main"></main>
     <div data-test="footer-player" id="footer"></div>
   </body></html>`,
  { url: "https://desktop.tidal.com/home", runScripts: "outside-only", pretendToBeVisual: true },
);
const { window } = dom;
const doc = window.document;

const fmt = (s) => {
  s = Math.max(0, Math.floor(s));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};
const position = () => {
  if (!state.current) return 0;
  if (!state.playing) return state.pausedPos;
  return Math.min(state.current.duration, (Date.now() - state.startedWall) / 1000);
};

function renderFooter() {
  const f = doc.getElementById("footer");
  const t = state.current;
  const ctl = state.playing
    ? `<button data-test="pause" aria-label="Pause"></button>`
    : `<button data-test="play" aria-label="Play"></button>`;
  f.innerHTML = t
    ? `<a href="/album/${t.album_id}/track/${t.id}"><span data-test="footer-track-title">${t.title}</span></a>
       <a data-test="footer-artist-name" href="/artist/${t.artist_id}">${t.artist}</a>
       <div class="time"><time>${fmt(position())}</time><span> / </span><time>${fmt(t.duration)}</time></div>
       <div data-test="play-controls"><button data-test="previous" aria-label="Previous"></button>${ctl}<button data-test="next" aria-label="Next"></button></div>`
    : `<div data-test="play-controls"><button data-test="play" aria-label="Play"></button></div>`;
  const controls = f.querySelector("[data-test=play-controls]");
  controls.querySelector("[data-test=pause]")?.addEventListener("click", () => pause());
  controls.querySelector("[data-test=play]")?.addEventListener("click", () => resume());
  controls.querySelector("[data-test=next]")?.addEventListener("click", () => advance("next-button"));
}

function play(id, how) {
  const t = byId[id];
  if (!t) throw new Error(`unknown track ${id}`);
  state.current = t;
  state.playing = true;
  state.startedWall = Date.now();
  state.pausedPos = 0;
  state.played.push({ id, how, at: Date.now() });
  log(`play ${id} (${t.title} - ${t.artist}) via ${how}`);
  renderFooter();
}
function pause() {
  if (!state.playing) return;
  state.pausedPos = position();
  state.playing = false;
  renderFooter();
}
function resume() {
  if (!state.current || state.playing) return;
  state.startedWall = Date.now() - state.pausedPos * 1000;
  state.playing = true;
  renderFooter();
}
function advance(how) {
  // What TIDAL does on its own when a song ends: next track of the album.
  const next = state.current?.auto_next || catalog.filler_id;
  play(next, how);
}

// --- single page app routing -------------------------------------------------
let renderTimer = null;
function route() {
  const m = window.location.pathname.match(/^\/track\/(\d+)$/);
  const main = doc.getElementById("main");
  main.innerHTML = "";
  clearTimeout(renderTimer);
  if (!m) return;
  const t = byId[m[1]];
  if (!t) return;
  // The track page renders its album's track list after a short "network" delay.
  renderTimer = setTimeout(() => {
    const rows = [t.id, ...(t.album_tracks || [])].map((id) => byId[id]).filter(Boolean);
    main.innerHTML =
      `<button aria-label="Play" data-test="hero-play"></button>` +
      rows
        .map((r) => `<div data-test="tracklist-row"><button data-test="play-button" aria-label="Play" data-id="${r.id}"></button>` +
                    `<a href="/track/${r.id}">${r.title}</a><span>${r.artist}</span></div>`)
        .join("");
    main.querySelectorAll("[data-test=play-button]").forEach((b) =>
      b.addEventListener("click", () => play(b.getAttribute("data-id"), "row-click")));
  }, 300);
}
window.addEventListener("popstate", route);

setInterval(() => {
  if (state.current && state.playing && position() >= state.current.duration) advance("auto");
  else renderFooter();
}, 100);
renderFooter();

// --- HTTP + CDP ----------------------------------------------------------------
const json = (res, code, body) => {
  res.writeHead(code, { "Content-Type": "application/json" });
  res.end(JSON.stringify(body));
};

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://127.0.0.1:${port}`);
  const q = Object.fromEntries(url.searchParams);
  try {
    if (url.pathname === "/json/version")
      return json(res, 200, { Browser: "Chrome/120.0.0.0", "Protocol-Version": "1.3", "User-Agent": "TIDAL/2.43 Electron" });
    if (url.pathname === "/json" || url.pathname === "/json/list")
      return json(res, 200, [
        { type: "service_worker", url: "https://desktop.tidal.com/sw.js", webSocketDebuggerUrl: `ws://127.0.0.1:${port}/devtools/page/sw` },
        { type: "page", title: "TIDAL", url: window.location.href, webSocketDebuggerUrl: `ws://127.0.0.1:${port}/devtools/page/1` },
      ]);
    if (url.pathname === "/__state")
      return json(res, 200, {
        track: state.current, playing: state.playing, elapsed: position(),
        nowMicros: Date.now() * 1000, playedCount: state.played.length, path: window.location.pathname,
      });
    if (url.pathname === "/__played") return json(res, 200, state.played);
    if (url.pathname === "/__opened") return json(res, 200, state.opened);
    if (url.pathname === "/__play") { play(q.id, q.how || "user"); return json(res, 200, { ok: true }); }
    if (url.pathname === "/__pause") { pause(); return json(res, 200, { ok: true }); }
    if (url.pathname === "/__open") {
      // tidal://track/<id> only navigates, exactly like the real app.
      state.opened.push(q.url);
      const m = (q.url || "").match(/track\/(\d+)/);
      if (m) { window.history.pushState({}, "", `/track/${m[1]}`); route(); }
      return json(res, 200, { ok: true });
    }
    if (url.pathname === "/__quit") { json(res, 200, { ok: true }); setTimeout(() => process.exit(0), 50); return; }
    if (url.pathname === "/odesli") {
      // song.link stand-in: map a TIDAL url to the Spotify id from the catalog
      const m = (q.url || "").match(/track\/(\d+)/);
      const t = m && byId[m[1]];
      if (!t || !t.spotify) return json(res, 404, { statusCode: 404, code: "could_not_resolve_entity" });
      return json(res, 200, {
        entityUniqueId: `TIDAL_SONG::${t.id}`,
        linksByPlatform: {
          spotify: { url: `https://open.spotify.com/track/${t.spotify}`, entityUniqueId: `SPOTIFY_SONG::${t.spotify}` },
          tidal: { url: `https://listen.tidal.com/track/${t.id}`, entityUniqueId: `TIDAL_SONG::${t.id}` },
        },
        entitiesByUniqueId: {
          [`SPOTIFY_SONG::${t.spotify}`]: { id: t.spotify, type: "song", title: t.title, artistName: t.artist },
          [`TIDAL_SONG::${t.id}`]: { id: t.id, type: "song", title: t.title, artistName: t.artist },
        },
      });
    }
    json(res, 404, { error: "not found" });
  } catch (e) {
    json(res, 500, { error: String(e) });
  }
});

const wss = new WebSocketServer({ noServer: true });
server.on("upgrade", (req, socket, head) => {
  if (req.headers.origin) {
    // Chromium: "Rejected an incoming WebSocket connection from the http://... origin"
    socket.write("HTTP/1.1 403 Forbidden\r\n\r\n");
    socket.destroy();
    log(`rejected websocket with Origin ${req.headers.origin}`);
    return;
  }
  if (!req.url.startsWith("/devtools/page/1")) { socket.destroy(); return; }
  wss.handleUpgrade(req, socket, head, (ws) => wss.emit("connection", ws));
});

wss.on("connection", (ws) => {
  ws.on("message", async (raw) => {
    const msg = JSON.parse(raw.toString());
    if (msg.method !== "Runtime.evaluate") return ws.send(JSON.stringify({ id: msg.id, result: {} }));
    const { expression, returnByValue, awaitPromise } = msg.params || {};
    try {
      let value = window.eval(expression);
      if (awaitPromise && value && typeof value.then === "function") value = await value;
      const result = value === undefined
        ? { type: "undefined" }
        : { type: typeof value, value: returnByValue ? JSON.parse(JSON.stringify(value)) : undefined };
      ws.send(JSON.stringify({ id: msg.id, result: { result } }));
    } catch (e) {
      ws.send(JSON.stringify({ id: msg.id, result: {
        result: { type: "object", subtype: "error", description: String(e) },
        exceptionDetails: { text: "Uncaught", exception: { description: (e && e.stack) || String(e) } },
      } }));
    }
  });
});

server.listen(port, "127.0.0.1", () => log(`fake TIDAL listening on ${port}`));
