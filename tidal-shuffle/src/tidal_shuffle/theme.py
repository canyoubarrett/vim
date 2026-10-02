"""Catppuccin (https://catppuccin.com) for the full-screen view.

The four flavors, with the official hex values from catppuccin/palette, and
the roles the view uses them for.
"""

from __future__ import annotations

from dataclasses import dataclass, field

Color = tuple[int, int, int]

PALETTES: dict[str, dict[str, str]] = {
    "latte": {
        "rosewater": "#dc8a78", "flamingo": "#dd7878", "pink": "#ea76cb", "mauve": "#8839ef", "red": "#d20f39",
        "maroon": "#e64553", "peach": "#fe640b", "yellow": "#df8e1d", "green": "#40a02b", "teal": "#179299",
        "sky": "#04a5e5", "sapphire": "#209fb5", "blue": "#1e66f5", "lavender": "#7287fd", "text": "#4c4f69",
        "subtext1": "#5c5f77", "subtext0": "#6c6f85", "overlay2": "#7c7f93", "overlay1": "#8c8fa1",
        "overlay0": "#9ca0b0", "surface2": "#acb0be", "surface1": "#bcc0cc", "surface0": "#ccd0da",
        "base": "#eff1f5", "mantle": "#e6e9ef", "crust": "#dce0e8",
    },
    "frappe": {
        "rosewater": "#f2d5cf", "flamingo": "#eebebe", "pink": "#f4b8e4", "mauve": "#ca9ee6", "red": "#e78284",
        "maroon": "#ea999c", "peach": "#ef9f76", "yellow": "#e5c890", "green": "#a6d189", "teal": "#81c8be",
        "sky": "#99d1db", "sapphire": "#85c1dc", "blue": "#8caaee", "lavender": "#babbf1", "text": "#c6d0f5",
        "subtext1": "#b5bfe2", "subtext0": "#a5adce", "overlay2": "#949cbb", "overlay1": "#838ba7",
        "overlay0": "#737994", "surface2": "#626880", "surface1": "#51576d", "surface0": "#414559",
        "base": "#303446", "mantle": "#292c3c", "crust": "#232634",
    },
    "macchiato": {
        "rosewater": "#f4dbd6", "flamingo": "#f0c6c6", "pink": "#f5bde6", "mauve": "#c6a0f6", "red": "#ed8796",
        "maroon": "#ee99a0", "peach": "#f5a97f", "yellow": "#eed49f", "green": "#a6da95", "teal": "#8bd5ca",
        "sky": "#91d7e3", "sapphire": "#7dc4e4", "blue": "#8aadf4", "lavender": "#b7bdf8", "text": "#cad3f5",
        "subtext1": "#b8c0e0", "subtext0": "#a5adcb", "overlay2": "#939ab7", "overlay1": "#8087a2",
        "overlay0": "#6e738d", "surface2": "#5b6078", "surface1": "#494d64", "surface0": "#363a4f",
        "base": "#24273a", "mantle": "#1e2030", "crust": "#181926",
    },
    "mocha": {
        "rosewater": "#f5e0dc", "flamingo": "#f2cdcd", "pink": "#f5c2e7", "mauve": "#cba6f7", "red": "#f38ba8",
        "maroon": "#eba0ac", "peach": "#fab387", "yellow": "#f9e2af", "green": "#a6e3a1", "teal": "#94e2d5",
        "sky": "#89dceb", "sapphire": "#74c7ec", "blue": "#89b4fa", "lavender": "#b4befe", "text": "#cdd6f4",
        "subtext1": "#bac2de", "subtext0": "#a6adc8", "overlay2": "#9399b2", "overlay1": "#7f849c",
        "overlay0": "#6c7086", "surface2": "#585b70", "surface1": "#45475a", "surface0": "#313244",
        "base": "#1e1e2e", "mantle": "#181825", "crust": "#11111b",
    },
}
FLAVORS = tuple(PALETTES)


def hex_rgb(h: str) -> Color:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


@dataclass(frozen=True)
class Theme:
    name: str
    bg: Color             # base: the whole screen
    border: Color         # panel borders
    title: Color          # panel titles, the logo
    text: Color
    subtle: Color         # secondary text
    faint: Color          # timestamps, separators
    past: Color           # lyrics already sung
    current_bg: Color     # the line being sung: inverted
    current_fg: Color
    playing: Color        # ▶
    paused: Color         # ⏸
    bar: Color            # progress done
    bar_rest: Color
    knob: Color
    logo: Color
    logo_glow: Color
    shadow: Color
    p: dict = field(default_factory=dict, compare=False)   # the whole flavor: p["peach"], p["surface0"], ...


def theme(flavor: str = "mocha") -> Theme:
    p = {k: hex_rgb(v) for k, v in PALETTES.get(flavor, PALETTES["mocha"]).items()}
    return Theme(
        name=flavor if flavor in PALETTES else "mocha",
        bg=p["base"], border=p["surface1"], title=p["mauve"], text=p["text"], subtle=p["subtext0"],
        faint=p["overlay0"], past=p["overlay1"], current_bg=p["mauve"], current_fg=p["crust"],
        playing=p["green"], paused=p["yellow"], bar=p["lavender"], bar_rest=p["surface1"], knob=p["pink"],
        logo=p["mauve"], logo_glow=p["pink"], shadow=p["surface1"], p=p,
    )
