"""Alter Era house style for the Tidal Shuffle manuals: a diagram-design skin
in the manner of Dieter Rams (Braun): warm greys, one orange, grotesk type,
hairlines, nothing that is not needed.

Diagram primitives follow diagram-design 2.6 (SKILL.md §6): paper mask under
every node, rx<=6, mono type tags, orthogonal r=8 elbows, label masks with a
6-10px gap, arrows drawn before nodes, accessible <title>/<desc>."""

from __future__ import annotations

import html
import re
from pathlib import Path

HERE = Path(__file__).parent
LOGO_FILE = HERE.parents[2] / "src" / "tidal_shuffle" / "assets" / "alter-era-flat.svg"

# -- tokens (diagram-design semantic roles, Alter Era / Rams skin) -------------
PAPER = "#f2f1ed"      # paper: warm light grey, like a Braun panel
PAPER2 = "#e7e6e1"     # paper-2
CARD = "#fbfbf9"       # backend node fill (near white)
INK = "#22221f"        # ink: anthracite
MUTED = "#5b5a55"      # muted
SOFT = "#8b8a84"       # soft
RULE = "rgba(34,34,31,0.14)"
ACCENT = "#e2611f"     # the one orange
TINT = "rgba(226,97,31,0.08)"
LINK = "#4d7349"       # link role: external services (Braun's olive green)
SANS = "'Inter Tight', 'Helvetica Neue', Helvetica, Arial, sans-serif"
MONO = "'Geist Mono', ui-monospace, Menlo, monospace"

E = html.escape


def fonts_css() -> str:
    return (HERE / "fonts.css").read_text()


# -- the logo -------------------------------------------------------------------
def _logo_paths() -> list[tuple[str, str]]:
    svg = LOGO_FILE.read_text()
    return re.findall(r'<path d="([^"]+)" fill="(#[0-9a-fA-F]{6})"', svg)


def logo(size: int, mono: str | None = None, opacity: float = 1.0, label: str = "Alter Era") -> str:
    """The Alter Era mark: in its own colours, or in one colour (``mono``)."""
    paths = "".join(f'<path d="{d}" fill="{mono or fill}"/>' for d, fill in _logo_paths())
    w = round(size * 252 / 370)
    aria = f'role="img" aria-label="{E(label)}"' if label else 'aria-hidden="true"'
    return (f'<svg {aria} width="{w}" height="{size}" viewBox="124 64 252 370" '
            f'style="opacity:{opacity}">{paths}</svg>')


def watermark() -> str:
    return f'<div class="watermark" aria-hidden="true">{logo(560, mono=INK, label="")}</div>'


# -- diagram primitives -----------------------------------------------------------
def tw(text: str, size: float = 8.0) -> float:
    """Approximate width of mono caps at ``size`` with 0.06em tracking."""
    return len(text) * size * 0.66


class Diagram:
    def __init__(self, slug: str, width: int, height: int, title: str, desc: str):
        self.slug, self.w, self.h, self.title, self.desc = slug, width, height, title, desc
        self.back: list[str] = []      # zones
        self.arrows: list[str] = []
        self.labels: list[str] = []
        self.nodes: list[str] = []
        self.front: list[str] = []     # legend, notes

    # markers are prefixed per diagram: several diagrams share one HTML page
    def m(self, kind: str = "arrow") -> str:
        return f"url(#{self.slug}-{kind})"

    def svg(self) -> str:
        s = self.slug
        defs = "".join(
            f'<marker id="{s}-{k}" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">'
            f'<polygon points="0 0, 8 3, 0 6" fill="{c}"/></marker>'
            for k, c in (("arrow", MUTED), ("arrow-accent", ACCENT), ("arrow-link", LINK)))
        defs += (f'<marker id="{s}-open" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">'
                 f'<polyline points="0 0, 8 3, 0 6" fill="none" stroke="{MUTED}" stroke-width="1"/></marker>')
        body = "\n".join(self.back + self.arrows + self.labels + self.nodes + self.front)
        return (f'<svg role="img" aria-labelledby="{s}-title {s}-desc" viewBox="0 0 {self.w} {self.h}" '
                f'style="min-width:{self.w}px" xmlns="http://www.w3.org/2000/svg">\n'
                f'<title id="{s}-title">{E(self.title)}</title>\n<desc id="{s}-desc">{E(self.desc)}</desc>\n'
                f'<defs>{defs}</defs>\n<rect width="100%" height="100%" fill="{PAPER}"/>\n{body}\n</svg>')

    # -- nodes
    def node(self, x, y, w, h, name, sub=(), tag=None, kind="backend", name_size=12):
        fill, stroke, dash = {
            "backend": (CARD, INK, ""),
            "focal": (TINT, ACCENT, ""),
            "store": ("rgba(34,34,31,0.05)", MUTED, ""),
            "external": ("rgba(34,34,31,0.03)", "rgba(34,34,31,0.30)", ""),
            "input": ("rgba(91,90,85,0.10)", SOFT, ""),
            "optional": ("rgba(34,34,31,0.02)", "rgba(34,34,31,0.20)", ' stroke-dasharray="4,3"'),
            "user": (INK, INK, ""),
        }[kind]
        text = PAPER if kind == "user" else INK
        subc = "rgba(242,241,237,0.72)" if kind == "user" else MUTED
        out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="4" fill="{PAPER}"/>',
               f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="4" fill="{fill}" stroke="{stroke}" stroke-width="1"{dash}/>']
        if tag:
            tw_ = round(len(tag) * 5.2 + 10)
            tc = ACCENT if kind == "focal" else (PAPER if kind == "user" else MUTED)
            out.append(f'<rect x="{x + 8}" y="{y + 6}" width="{tw_}" height="12" rx="2" fill="none" '
                       f'stroke="{tc}" stroke-opacity="0.45" stroke-width="0.8"/>')
            out.append(f'<text x="{x + 8 + tw_ / 2}" y="{y + 14.5}" fill="{tc}" font-size="7" font-family="{MONO}" '
                       f'text-anchor="middle" letter-spacing="0.08em">{E(tag)}</text>')
        sub = [sub] if isinstance(sub, str) else list(sub)
        cx = x + w / 2
        top = y + (14 if tag else 0)
        block = name_size + len(sub) * 12
        ny = top + (h - (14 if tag else 0)) / 2 - block / 2 + name_size * 0.85
        out.append(f'<text x="{cx}" y="{ny:.1f}" fill="{text}" font-size="{name_size}" font-weight="500" '
                   f'font-family="{SANS}" text-anchor="middle">{E(name)}</text>')
        for i, line in enumerate(sub):
            out.append(f'<text x="{cx}" y="{ny + 14 + i * 12:.1f}" fill="{subc}" font-size="8.5" '
                       f'font-family="{MONO}" text-anchor="middle">{E(line)}</text>')
        self.nodes.append("\n".join(out))

    # -- connectors
    @staticmethod
    def elbow(pts, r=8) -> str:
        def sg(v):
            return (v > 0) - (v < 0)
        d = f"M{pts[0][0]},{pts[0][1]}"
        for i in range(1, len(pts) - 1):
            (x0, y0), (x1, y1), (x2, y2) = pts[i - 1], pts[i], pts[i + 1]
            a = (x1 - sg(x1 - x0) * r, y1 - sg(y1 - y0) * r)
            b = (x1 + sg(x2 - x1) * r, y1 + sg(y2 - y1) * r)
            sweep = 1 if sg(x1 - x0) * sg(y2 - y1) - sg(y1 - y0) * sg(x2 - x1) > 0 else 0
            d += f" L{a[0]},{a[1]} A{r},{r} 0 0 {sweep} {b[0]},{b[1]}"
        return d + f" L{pts[-1][0]},{pts[-1][1]}"

    def arrow(self, pts, kind="arrow", dashed=False, marker=True):
        color = {"arrow": MUTED, "arrow-accent": ACCENT, "arrow-link": LINK, "open": MUTED}[kind]
        width = 1.3 if kind == "arrow-accent" else 1
        dash = ' stroke-dasharray="5,4"' if dashed else ""
        mk = f' marker-end="{self.m(kind)}"' if marker else ""
        self.arrows.append(f'<path d="{self.elbow(pts)}" fill="none" stroke="{color}" stroke-width="{width}"{dash}{mk}/>')

    def label(self, x, y_line, text, where="above"):
        """A mono caps label on an opaque plate, 8px clear of its connector.
        ``where``: above / below a horizontal segment at y_line, or right / left
        of a vertical one at x (then y_line is the label's middle)."""
        w = round(tw(text) + 10)
        if where in ("above", "below"):
            top = y_line - 20 if where == "above" else y_line + 8
            rx, ty, tx = x - w / 2, top + 9, x
        else:
            top = y_line - 6
            rx = x + 8 if where == "right" else x - 8 - w
            tx, ty = rx + w / 2, top + 9
        self.labels.append(f'<rect x="{rx:.1f}" y="{top:.1f}" width="{w}" height="12" rx="2" fill="{PAPER}"/>'
                           f'<text x="{tx:.1f}" y="{ty:.1f}" fill="{SOFT}" font-size="8" font-family="{MONO}" '
                           f'text-anchor="middle" letter-spacing="0.06em">{E(text)}</text>')

    def legend(self, y, items):
        """A horizontal strip under the drawing: (swatch kind, text)."""
        out = [f'<line x1="24" y1="{y - 8}" x2="{self.w - 24}" y2="{y - 8}" stroke="{RULE}" stroke-width="0.8"/>',
               f'<text x="24" y="{y + 10}" fill="{MUTED}" font-size="8" font-family="{MONO}" letter-spacing="0.14em">LEGEND</text>']
        x = 96
        for kind, text in items:
            if kind in ("focal", "backend", "external", "user", "store", "optional"):
                fill, stroke = {"focal": (TINT, ACCENT), "backend": (CARD, INK), "external": ("rgba(34,34,31,0.03)", "rgba(34,34,31,0.30)"),
                                "user": (INK, INK), "store": ("rgba(34,34,31,0.05)", MUTED),
                                "optional": ("rgba(34,34,31,0.02)", "rgba(34,34,31,0.20)")}[kind]
                out.append(f'<rect x="{x}" y="{y + 2}" width="14" height="10" rx="2" fill="{fill}" stroke="{stroke}" stroke-width="1"/>')
            else:
                color = {"arrow": MUTED, "arrow-accent": ACCENT, "arrow-link": LINK, "dashed": MUTED}[kind]
                dash = ' stroke-dasharray="5,4"' if kind == "dashed" else ""
                out.append(f'<line x1="{x}" y1="{y + 7}" x2="{x + 18}" y2="{y + 7}" stroke="{color}" stroke-width="1.2"{dash}/>')
            out.append(f'<text x="{x + 22}" y="{y + 10}" fill="{MUTED}" font-size="8.5" font-family="{SANS}">{E(text)}</text>')
            x += 22 + len(text) * 4.6 + 26
        self.front.append("\n".join(out))

    def text(self, x, y, s, size=9, color=MUTED, mono=False, anchor="start", weight=400, italic=False, spacing=None):
        fam = MONO if mono else SANS
        ls = f' letter-spacing="{spacing}"' if spacing else ""
        it = ' font-style="italic"' if italic else ""
        self.front.append(f'<text x="{x}" y="{y}" fill="{color}" font-size="{size}" font-weight="{weight}" '
                          f'font-family="{fam}" text-anchor="{anchor}"{ls}{it}>{E(s)}</text>')


def keycap(k: str) -> str:
    return f'<span class="key">{E(k)}</span>'
