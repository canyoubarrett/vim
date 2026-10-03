"""The manual's figures, drawn on a 4px grid in the Alter Era skin."""

from __future__ import annotations

from kit import ACCENT, CARD, INK, MONO, MUTED, PAPER, PAPER2, RULE, SANS, SOFT, TINT, Diagram, E, logo


def architecture(slug="fig-architecture") -> str:
    """Architecture: what talks to what."""
    d = Diagram(slug, 688, 512, "Tidal Shuffle system overview",
                "Tidal Shuffle's loop follows the song macOS reports, asks its engine for the next song "
                "(recommendation sources, then the TIDAL catalog), and makes the TIDAL app play it.")
    # arrows first
    d.arrow([(144, 180), (212, 180)])
    d.label(178, 180, "KEYS")
    d.arrow([(464, 180), (364, 180)])
    d.label(414, 180, "NOW PLAYING")
    d.arrow([(288, 152), (288, 68), (464, 68)], kind="arrow-accent")
    d.label(380, 68, "PLAY THE PICK")
    d.arrow([(564, 96), (564, 152)], dashed=True)
    d.label(564, 124, "REPORTS", where="right")
    d.arrow([(288, 208), (288, 268)])
    d.label(288, 238, "PLAN", where="right")
    d.arrow([(364, 300), (464, 300)], kind="arrow-link")
    d.label(414, 300, "ASK")
    d.arrow([(288, 332), (288, 388)], kind="arrow-link")
    d.label(288, 360, "FIND", where="right")
    # nodes
    d.node(24, 152, 120, 56, "You", "keys · mouse · media", kind="user")
    d.node(212, 152, 152, 56, "Shuffle loop", "follows · hands off", tag="CORE", kind="focal")
    d.node(212, 268, 152, 64, "Choosing engine", ["sources → pool → order", "→ find on TIDAL"], tag="ENGINE")
    d.node(212, 388, 152, 56, "TIDAL catalog", "search · ISRC · radio", kind="external")
    d.node(464, 40, 200, 56, "TIDAL app", "debug port 127.0.0.1:9222", tag="APP", kind="external")
    d.node(464, 152, 200, 56, "macOS Now Playing", "media-control", kind="external")
    d.node(464, 268, 200, 64, "Recommendation sources", ["Spotify app (hidden, muted)", "Spotify API · Last.fm · Deezer"],
           kind="external")
    d.legend(480, [("user", "You"), ("focal", "Core"), ("backend", "Tidal Shuffle"), ("external", "Outside it"),
                   ("arrow-accent", "Main path"), ("arrow-link", "Web call"), ("dashed", "Passive")])
    return d.svg()


def timeline(slug="fig-timeline", compact=False) -> str:
    """Timeline: one song, from its start to the pick taking over (axis broken)."""
    d = Diagram(slug, 688, 216, "One song, from start to hand-off",
                "Four seconds into a song the next one is chosen; ten seconds before its end the pick's page "
                "is opened; 0.8 seconds before the end TIDAL is held; at the end the pick starts and is verified.")
    y = 116
    # the axis: the start of the song, a break, its last seconds and the hand-off
    d.back.append(f'<line x1="24" y1="{y}" x2="292" y2="{y}" stroke="{INK}" stroke-width="1"/>')
    d.back.append(f'<line x1="316" y1="{y}" x2="664" y2="{y}" stroke="{INK}" stroke-width="1"/>')
    d.back.append(f'<path d="M290,{y + 6} L296,{y - 6} M312,{y + 6} L318,{y - 6}" stroke="{SOFT}" stroke-width="1"/>')
    s1, s2, end = 8.8, 17.6, 528            # px per second: start segment, end segment; the song's end
    events = [  # x, name, sub, above, anchor, focal
        (24 + 4 * s1, "Choose the next song", "0:04 · and the one after it", True, "start", False),
        (end - 10 * s2, "Open the pick's page", "end − 10 s · loads it", False, "start", False),
        (end - 0.8 * s2, "Hold TIDAL", "end − 0.8 s · pause", True, "end", False),
        (end, "Start the pick", "end · confirmed within 8 s", False, "start", True),
    ]
    for x, name, sub, above, anchor, focal in events:
        x = round(x, 1)
        if above:
            d.back.append(f'<line x1="{x}" y1="{y - 34}" x2="{x}" y2="{y - 6}" stroke="{RULE}" stroke-width="1"/>')
            ny, sy = y - 54, y - 42
        else:
            d.back.append(f'<line x1="{x}" y1="{y + 6}" x2="{x}" y2="{y + 34}" stroke="{RULE}" stroke-width="1"/>')
            ny, sy = y + 50, y + 62
        r, fill = (6, ACCENT) if focal else (4, INK)
        d.nodes.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}"/>')
        d.text(x, ny, name, size=11, color=INK, anchor=anchor, weight=500)
        d.text(x, sy, sub, size=8.5, color=MUTED, mono=True, anchor=anchor)
    d.nodes.append(f'<circle cx="24" cy="{y}" r="3" fill="{PAPER}" stroke="{INK}" stroke-width="1"/>')
    d.text(24, y + 24, "song starts", size=8.5, color=SOFT, mono=True)
    d.text(664, y + 24, "+8 s", size=8.5, color=SOFT, mono=True, anchor="end")
    d.text(24, 200, "time →  (the middle of the song is left out; each side is to scale)", size=8.5, color=SOFT, mono=True)
    return d.svg()


def funnel(slug="fig-funnel") -> str:
    """Funnel: from the radio's songs to one pick and two backups (an example run)."""
    d = Diagram(slug, 688, 300, "How the next song is chosen",
                "In an example run, 30 songs from the sources become 24 after cleaning; six are looked up "
                "on TIDAL in order and the first three that fit become the pick and two backups.")
    layers = [  # count, name, sub
        (30, "Ask the sources", "Spotify radio first"),
        (24, "Clean the pool", "repeats, look-alikes out"),
        (6, "Order, find on TIDAL", "four lookups at once"),
        (3, "Pick + two backups", "the first three that fit"),
    ]
    cx, full, top, h, gap = 472, 384, 24, 52, 8
    for i, (n, name, sub) in enumerate(layers):
        y = top + i * (h + gap)
        w0 = full * n / 30
        w1 = full * (layers[i + 1][0] / 30 if i + 1 < len(layers) else n * 0.7 / 30)
        focal = i == len(layers) - 1
        fill, stroke = (TINT, ACCENT) if focal else (PAPER2, MUTED)
        pts = f"{cx - w0 / 2:.1f},{y} {cx + w0 / 2:.1f},{y} {cx + w1 / 2:.1f},{y + h} {cx - w1 / 2:.1f},{y + h}"
        d.nodes.append(f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="1"/>')
        d.text(24, y + 22, name, size=12, color=INK, weight=500)
        d.text(24, y + 37, sub, size=8.5, color=MUTED, mono=True)
        d.text(256, y + 33, str(n), size=20, color=ACCENT if focal else INK, anchor="end", weight=300)
    d.text(24, 272, "example run · widths are to scale", size=8.5, color=SOFT, mono=True)
    return d.svg()


def sequence(slug="fig-next") -> str:
    """Sequence: what happens when you press n."""
    d = Diagram(slug, 688, 372, "Pressing next",
                "Pressing n makes Tidal Shuffle hold TIDAL, open and play the pick, wait for macOS to report "
                "the new song, and find the song after it already chosen.")
    xs = {"you": 84, "ts": 264, "app": 444, "np": 604}
    names = {"you": ("You", "user"), "ts": ("Tidal Shuffle", "focal"), "app": ("TIDAL app", "external"),
             "np": ("Now Playing", "external")}
    for k, x in xs.items():
        d.back.append(f'<line x1="{x}" y1="64" x2="{x}" y2="352" stroke="{SOFT}" stroke-width="1" stroke-dasharray="4,4"/>')
    d.back.append(f'<rect x="{xs["ts"] - 4}" y="92" width="8" height="236" fill="{PAPER2}" stroke="{MUTED}" stroke-width="0.8"/>')
    L, R = xs["ts"] - 4, xs["ts"] + 4
    msgs = [  # y, from, to, label, kind, dashed
        (100, xs["you"], L, "PRESS N", "arrow", False),
        (136, R, xs["app"], "HOLD (PAUSE)", "arrow", False),
        (172, R, xs["app"], "OPEN ITS PAGE", "arrow", False),
        (208, R, xs["app"], "PLAY THE PICK", "arrow-accent", False),
        (244, xs["app"], xs["np"], "NEW SONG", "open", True),
        (280, xs["np"], R, "CONFIRMED", "arrow", True),
    ]
    for y, a, b, text, kind, dashed in msgs:
        d.arrow([(a, y), (b, y)], kind=kind, dashed=dashed)
        mid = (a + b) / 2 if text != "CONFIRMED" else (xs["app"] + xs["np"]) / 2
        d.label(mid, y, text)
    # self message: the song after the pick was chosen ahead
    d.arrow([(R, 304), (R + 40, 304), (R + 40, 324), (R, 324)])
    d.label(R + 40, 314, "NEXT IS READY", where="right")
    for k, x in xs.items():
        name, kind = names[k]
        d.node(x - 64, 20, 128, 44, name, kind=kind, name_size=11)
    return d.svg()


def screen_map(slug="fig-screen") -> str:
    """The full-screen view as a numbered drawing, like a product drawing."""
    d = Diagram(slug, 688, 336, "The full-screen view",
                "The screen is divided into a header, the logo, the lyrics, the log with Up next beside it, "
                "and a row of keys; Esc lays the settings over the left half.")
    d.back.append(f'<rect x="24" y="16" width="640" height="304" rx="6" fill="{CARD}" stroke="{INK}" stroke-width="1"/>')
    regions = [  # n, x, y, w, h, name
        (1, 40, 32, 608, 48, "Now playing · progress · source"),
        (2, 40, 88, 236, 148, "Logo (or cover, shuffle tree)"),
        (3, 284, 88, 364, 148, "Lyrics, as they are sung"),
        (4, 40, 244, 364, 48, "Log"),
        (5, 412, 244, 236, 48, "Up next · just played"),
    ]
    for n, x, y, w, h, name in regions:
        d.nodes.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="3" fill="{PAPER}" stroke="{SOFT}" stroke-width="0.8"/>')
        d.nodes.append(f'<circle cx="{x + 14}" cy="{y + 14}" r="8" fill="{INK}"/>'
                       f'<text x="{x + 14}" y="{y + 17.5}" fill="{PAPER}" font-size="9" font-family="{MONO}" '
                       f'text-anchor="middle">{n}</text>')
        d.nodes.append(f'<text x="{x + 30}" y="{y + 18}" fill="{MUTED}" font-size="9.5" font-family="{SANS}">{E(name)}</text>')
    # the logo, small, in its panel; a few lyric lines
    d.nodes.append(f'<g transform="translate(136,118)">{logo(96, label="")}</g>')
    for i, (w, c) in enumerate(((220, MUTED), (260, INK), (190, SOFT), (230, SOFT))):
        d.nodes.append(f'<rect x="{300}" y="{134 + i * 22}" width="{w}" height="6" rx="3" fill="{c}" opacity="{0.9 if c == INK else 0.45}"/>')
    d.nodes.append(f'<rect x="300" y="156" width="96" height="6" rx="3" fill="{ACCENT}"/>')
    # 6: the key row
    d.nodes.append(f'<circle cx="54" cy="306" r="8" fill="{INK}"/><text x="54" y="309.5" fill="{PAPER}" '
                   f'font-size="9" font-family="{MONO}" text-anchor="middle">6</text>')
    x = 70
    for k, lab in (("space", "play"), ("n", "next"), ("f", "flow"), ("p", "presets"), ("l", "lyrics"),
                   ("a", "cover"), ("t", "tree"), ("esc", "settings"), ("q", "quit")):
        kw = len(k) * 5.6 + 10
        d.nodes.append(f'<rect x="{x}" y="{299}" width="{kw:.0f}" height="14" rx="2" fill="{PAPER2}" stroke="{SOFT}" stroke-width="0.6"/>'
                       f'<text x="{x + kw / 2:.1f}" y="309" fill="{INK}" font-size="8" font-family="{MONO}" text-anchor="middle">{k}</text>'
                       f'<text x="{x + kw + 4:.1f}" y="309" fill="{MUTED}" font-size="8" font-family="{SANS}">{lab}</text>')
        x += kw + 4 + len(lab) * 4.4 + 14
    return d.svg()


def troubleshooting(slug="fig-fix") -> str:
    """Flowchart: when the music does not switch."""
    d = Diagram(slug, 688, 468, "When the music does not switch",
                "Run the doctor and fix what it marks; if songs cannot be started, send the inspect output; "
                "if TIDAL plays its own song first, use the pause hand-off; otherwise read the verbose log.")
    cx = 304

    def diamond(cy, lines, focal=False):
        hw, hh = 104, 36
        pts = f"{cx},{cy - hh} {cx + hw},{cy} {cx},{cy + hh} {cx - hw},{cy}"
        stroke, fill = (ACCENT, TINT) if focal else (INK, CARD)
        d.nodes.append(f'<polygon points="{pts}" fill="{PAPER}"/><polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="1"/>')
        for i, line in enumerate(lines):
            d.nodes.append(f'<text x="{cx}" y="{cy - 3 + i * 13 - (len(lines) - 1) * 6}" fill="{INK}" font-size="10.5" '
                           f'font-weight="500" font-family="{SANS}" text-anchor="middle">{E(line)}</text>')

    def oval(y, text):
        d.nodes.append(f'<rect x="{cx - 92}" y="{y}" width="184" height="36" rx="18" fill="{PAPER}"/>'
                       f'<rect x="{cx - 92}" y="{y}" width="184" height="36" rx="18" fill="{INK}"/>'
                       f'<text x="{cx}" y="{y + 22}" fill="{PAPER}" font-size="11" font-weight="500" '
                       f'font-family="{SANS}" text-anchor="middle">{E(text)}</text>')

    rows = [(116, ["doctor all", "green?"], "NO", "Fix what it marks", ["login · debug port", "media-control"], False),
            (228, ["log says “could", "not start”?"], "YES", "Send inspect output", ["tidal-shuffle inspect", "--watch 20"], True),
            (340, ["TIDAL plays its", "own song first?"], "YES", "Pause hand-off", ["player.handoff_mode:", "pause (default)"], False)]
    # arrows first
    d.arrow([(cx, 60), (cx, 80)])
    prev = 60
    for i, (cy, _, side, *_rest) in enumerate(rows):
        if i:
            d.arrow([(cx, rows[i - 1][0] + 36), (cx, cy - 36)])
            d.label(cx, (rows[i - 1][0] + 36 + cy - 36) / 2, "YES" if i == 1 else "NO", where="right")
        d.arrow([(cx + 104, cy), (464, cy)])
        d.label(436, cy, side)
    d.arrow([(cx, 376), (cx, 412)])
    d.label(cx, 394, "NO", where="right")
    oval(24, "The music does not switch")
    for cy, lines, side, name, sub, focal in rows:
        diamond(cy, lines)
        d.node(464, cy - 28, 200, 56, name, sub, kind="focal" if focal else "backend", name_size=11)
    oval(412, "Run with -v; read the log")
    return d.svg()


ALL = {"architecture": architecture, "timeline": timeline, "funnel": funnel, "sequence": sequence,
       "screen": screen_map, "fix": troubleshooting}
