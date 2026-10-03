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
    light: bool = False   # a light theme (dark text on a pale background)


def _mix(a: Color, b: Color, t: float) -> Color:
    return (round(a[0] + (b[0] - a[0]) * t), round(a[1] + (b[1] - a[1]) * t), round(a[2] + (b[2] - a[2]) * t))


# Other popular themes, from their published palettes, given the same roles as
# Catppuccin's (base, surfaces, overlays, text, accents). Missing in-between
# shades are mixed from their neighbours.
OTHER_THEMES: dict[str, dict[str, str]] = {
    "nord": dict(base="#2e3440", mantle="#292e39", crust="#242933", surface0="#3b4252", surface1="#434c5e",
                 surface2="#4c566a", overlay0="#616e88", text="#eceff4", subtext1="#e5e9f0", subtext0="#d8dee9",
                 red="#bf616a", orange="#d08770", yellow="#ebcb8b", green="#a3be8c", teal="#8fbcbb", sky="#88c0d0",
                 blue="#81a1c1", sapphire="#5e81ac", purple="#b48ead", pink="#c895bf"),
    "dracula": dict(base="#282a36", mantle="#21222c", crust="#191a21", surface0="#343746", surface1="#44475a",
                    surface2="#565a72", overlay0="#6272a4", text="#f8f8f2", red="#ff5555", orange="#ffb86c",
                    yellow="#f1fa8c", green="#50fa7b", teal="#8be9fd", sky="#8be9fd", blue="#6ea8fe",
                    purple="#bd93f9", pink="#ff79c6"),
    "gruvbox": dict(base="#282828", mantle="#1d2021", crust="#141617", surface0="#3c3836", surface1="#504945",
                    surface2="#665c54", overlay0="#7c6f64", text="#ebdbb2", subtext1="#d5c4a1", subtext0="#bdae93",
                    red="#fb4934", orange="#fe8019", yellow="#fabd2f", green="#b8bb26", teal="#8ec07c",
                    sky="#83a598", blue="#83a598", purple="#d3869b", pink="#d3869b"),
    "gruvbox-light": dict(base="#fbf1c7", mantle="#f2e5bc", crust="#ebdbb2", surface0="#ebdbb2", surface1="#d5c4a1",
                          surface2="#bdae93", overlay0="#a89984", text="#3c3836", subtext1="#504945",
                          subtext0="#665c54", red="#9d0006", orange="#af3a03", yellow="#b57614", green="#79740e",
                          teal="#427b58", sky="#076678", blue="#076678", purple="#8f3f71", pink="#b16286",
                          light="1"),
    "tokyo-night": dict(base="#1a1b26", mantle="#16161e", crust="#101014", surface0="#232433", surface1="#292e42",
                        surface2="#414868", overlay0="#565f89", text="#c0caf5", subtext1="#a9b1d6",
                        red="#f7768e", orange="#ff9e64", yellow="#e0af68", green="#9ece6a", teal="#1abc9c",
                        sky="#7dcfff", blue="#7aa2f7", purple="#bb9af7", pink="#ff007c"),
    "tokyo-storm": dict(base="#24283b", mantle="#1f2335", crust="#1b1e2d", surface0="#292e42", surface1="#3b4261",
                        surface2="#414868", overlay0="#565f89", text="#c0caf5", subtext1="#a9b1d6",
                        red="#f7768e", orange="#ff9e64", yellow="#e0af68", green="#9ece6a", teal="#1abc9c",
                        sky="#7dcfff", blue="#7aa2f7", purple="#bb9af7", pink="#ff007c"),
    "solarized-dark": dict(base="#002b36", mantle="#00252f", crust="#001e26", surface0="#073642", surface1="#0d4452",
                           surface2="#305660", overlay0="#586e75", text="#93a1a1", subtext1="#839496",
                           subtext0="#657b83", red="#dc322f", orange="#cb4b16", yellow="#b58900", green="#859900",
                           teal="#2aa198", sky="#2aa198", blue="#268bd2", purple="#6c71c4", pink="#d33682"),
    "solarized-light": dict(base="#fdf6e3", mantle="#f5efdc", crust="#eee8d5", surface0="#eee8d5", surface1="#e2dcc7",
                            surface2="#c9c4b2", overlay0="#93a1a1", text="#586e75", subtext1="#657b83",
                            subtext0="#839496", red="#dc322f", orange="#cb4b16", yellow="#b58900", green="#859900",
                            teal="#2aa198", sky="#2aa198", blue="#268bd2", purple="#6c71c4", pink="#d33682",
                            light="1"),
    "one-dark": dict(base="#282c34", mantle="#21252b", crust="#1b1f24", surface0="#2c313a", surface1="#3e4451",
                     surface2="#4b5263", overlay0="#5c6370", text="#abb2bf", subtext1="#9da5b4",
                     red="#e06c75", orange="#d19a66", yellow="#e5c07b", green="#98c379", teal="#56b6c2",
                     sky="#56b6c2", blue="#61afef", purple="#c678dd", pink="#e589c9"),
    "rose-pine": dict(base="#191724", mantle="#16141f", crust="#121019", surface0="#1f1d2e", surface1="#26233a",
                      surface2="#403d52", overlay0="#6e6a86", text="#e0def4", subtext1="#908caa",
                      red="#eb6f92", orange="#ebbcba", yellow="#f6c177", green="#31748f", teal="#9ccfd8",
                      sky="#9ccfd8", blue="#31748f", purple="#c4a7e7", pink="#ebbcba"),
    "rose-pine-moon": dict(base="#232136", mantle="#1f1d30", crust="#1a1829", surface0="#2a273f", surface1="#393552",
                           surface2="#44415a", overlay0="#6e6a86", text="#e0def4", subtext1="#908caa",
                           red="#eb6f92", orange="#ea9a97", yellow="#f6c177", green="#3e8fb0", teal="#9ccfd8",
                           sky="#9ccfd8", blue="#3e8fb0", purple="#c4a7e7", pink="#ea9a97"),
    "rose-pine-dawn": dict(base="#faf4ed", mantle="#fffaf3", crust="#f2e9e1", surface0="#f2e9e1", surface1="#dfdad9",
                           surface2="#cecacd", overlay0="#9893a5", text="#575279", subtext1="#797593",
                           red="#b4637a", orange="#d7827e", yellow="#ea9d34", green="#286983", teal="#56949f",
                           sky="#56949f", blue="#286983", purple="#907aa9", pink="#d7827e", light="1"),
    "everforest": dict(base="#2d353b", mantle="#272e33", crust="#232a2e", surface0="#343f44", surface1="#3d484d",
                       surface2="#475258", overlay0="#7a8478", text="#d3c6aa", subtext1="#9da9a0",
                       subtext0="#859289", red="#e67e80", orange="#e69875", yellow="#dbbc7f", green="#a7c080",
                       teal="#83c092", sky="#7fbbb3", blue="#7fbbb3", purple="#d699b6", pink="#d699b6"),
    "kanagawa": dict(base="#1f1f28", mantle="#1a1a22", crust="#16161d", surface0="#2a2a37", surface1="#363646",
                     surface2="#54546d", overlay0="#727169", text="#dcd7ba", subtext1="#c8c093",
                     red="#e46876", orange="#ffa066", yellow="#e6c384", green="#98bb6c", teal="#7aa89f",
                     sky="#7fb4ca", blue="#7e9cd8", purple="#957fb8", pink="#d27e99"),
    "monokai": dict(base="#272822", mantle="#1e1f1c", crust="#171814", surface0="#3e3d32", surface1="#49483e",
                    surface2="#5b5a4f", overlay0="#75715e", text="#f8f8f2", subtext1="#cfcfc2",
                    red="#f92672", orange="#fd971f", yellow="#e6db74", green="#a6e22e", teal="#66d9ef",
                    sky="#66d9ef", blue="#66d9ef", purple="#ae81ff", pink="#f92672"),
    "github-dark": dict(base="#0d1117", mantle="#090c10", crust="#010409", surface0="#161b22", surface1="#21262d",
                        surface2="#30363d", overlay0="#6e7681", text="#e6edf3", subtext1="#c9d1d9",
                        subtext0="#8b949e", red="#ff7b72", orange="#ffa657", yellow="#d29922", green="#3fb950",
                        teal="#39c5cf", sky="#79c0ff", blue="#58a6ff", purple="#d2a8ff", pink="#f778ba"),
}
LIGHT_THEMES = {"latte"} | {k for k, v in OTHER_THEMES.items() if v.get("light")}
THEMES = ("mocha", "macchiato", "frappe", "latte") + tuple(OTHER_THEMES)
THEME_LABELS = {"mocha": "Catppuccin Mocha", "macchiato": "Catppuccin Macchiato", "frappe": "Catppuccin Frappé",
                "latte": "Catppuccin Latte", "nord": "Nord", "dracula": "Dracula", "gruvbox": "Gruvbox",
                "gruvbox-light": "Gruvbox Light", "tokyo-night": "Tokyo Night", "tokyo-storm": "Tokyo Night Storm",
                "solarized-dark": "Solarized Dark", "solarized-light": "Solarized Light", "one-dark": "One Dark",
                "rose-pine": "Rosé Pine", "rose-pine-moon": "Rosé Pine Moon", "rose-pine-dawn": "Rosé Pine Dawn",
                "everforest": "Everforest", "kanagawa": "Kanagawa", "monokai": "Monokai", "github-dark": "GitHub Dark"}


def _palette(name: str) -> dict:
    """All of Catppuccin's colour roles for any theme."""
    if name in PALETTES:
        return {k: hex_rgb(v) for k, v in PALETTES[name].items()}
    spec = {k: hex_rgb(v) for k, v in OTHER_THEMES[name].items() if k != "light"}
    o0, tx = spec["overlay0"], spec["text"]
    p = dict(spec)
    p.setdefault("overlay1", _mix(o0, tx, 0.18))
    p.setdefault("overlay2", _mix(o0, tx, 0.34))
    p.setdefault("subtext0", _mix(o0, tx, 0.6))
    p.setdefault("subtext1", _mix(o0, tx, 0.8))
    p["peach"] = spec["orange"]
    p["mauve"] = spec["purple"]
    p.setdefault("maroon", _mix(spec["red"], spec["pink"], 0.35))
    p.setdefault("flamingo", _mix(spec["pink"], tx, 0.35))
    p.setdefault("rosewater", _mix(spec["pink"], tx, 0.6))
    p.setdefault("sapphire", _mix(spec["sky"], spec["blue"], 0.5))
    p.setdefault("lavender", _mix(spec["blue"], spec["purple"], 0.45))
    for k in ("orange", "purple"):
        p.pop(k, None)
    return p


def theme(flavor: str = "mocha") -> Theme:
    name = flavor if flavor in THEMES else "mocha"
    p = _palette(name)
    return Theme(
        name=name,
        bg=p["base"], border=p["surface1"], title=p["mauve"], text=p["text"], subtle=p["subtext0"],
        faint=p["overlay0"], past=p["overlay1"], current_bg=p["mauve"], current_fg=p["crust"],
        playing=p["green"], paused=p["yellow"], bar=p["lavender"], bar_rest=p["surface1"], knob=p["pink"],
        # the logo: a light, greyed lilac, breathing towards a paler one
        logo=_mix(p["mauve"], p["subtext1"], 0.55), logo_glow=_mix(p["mauve"], p["text"], 0.7),
        shadow=p["surface1"], p=p, light=name in LIGHT_THEMES,
    )


def blend(a: Theme, b: Theme, t: float) -> Theme:
    """A theme part way from ``a`` to ``b`` (for changing themes smoothly)."""
    if t <= 0:
        return a
    if t >= 1:
        return b
    from dataclasses import fields

    vals = {}
    for f in fields(Theme):
        x, y = getattr(a, f.name), getattr(b, f.name)
        if f.name == "p":
            vals["p"] = {k: _mix(x[k], y[k], t) for k in y}
        elif isinstance(x, tuple):
            vals[f.name] = _mix(x, y, t)
        else:
            vals[f.name] = y if t >= 0.5 else x
    return Theme(**vals)
