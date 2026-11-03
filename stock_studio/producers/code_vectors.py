"""Lane B - vectors generated from code.

Produces three kinds of original, editable vector assets, each set in one consistent style:
  * icon sets       - 9-12 icons from vector_icons.py on a clean sheet
  * seamless patterns - tiles that wrap at every edge, shown repeated on a swatch
  * infographic templates - steps, timeline, bar chart and cycle layouts with placeholder text
Each asset is written as SVG (master), EPS (via cairo, for upload) and a large JPEG preview.
"""
from __future__ import annotations

import hashlib
import io
import math
import random
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image

from ..config import Settings
from ..models import Asset, Lane
from ..store import Store
from .vector_icons import ICON_SETS, ICONS

# --------------------------------------------------------------------------- styles
PALETTES: dict[str, list[str]] = {
    # primary, secondary/tint, accent, dark, background
    "ceylon_tea": ["#2F6B3B", "#CFE6C8", "#E0A526", "#1D3B24", "#FFFFFF"],
    "sunset_coast": ["#E2603A", "#FBD8C6", "#1E8C93", "#5A2A1E", "#FFFFFF"],
    "lotus": ["#B4407A", "#F5D3E4", "#F2B33D", "#4E1B37", "#FFFFFF"],
    "monsoon": ["#22577A", "#C7E3F0", "#57CC99", "#0F2A3A", "#FFFFFF"],
    "spice_market": ["#B23A2E", "#F6D9B8", "#D98E04", "#4A1E16", "#FFFDF8"],
    "corporate_blue": ["#1F4FD1", "#D6E0FB", "#13B5A6", "#0C1A45", "#FFFFFF"],
    "mono_ink": ["#1B1B1F", "#E4E4E7", "#6B6B76", "#000000", "#FFFFFF"],
}
MODES = ["outline", "filled", "duotone"]
FONT = "Helvetica, Arial, sans-serif"


@dataclass
class VStyle:
    palette_name: str
    mode: str = "outline"
    stroke: float = 3.0

    @property
    def p(self) -> list[str]:
        return PALETTES[self.palette_name]

    @property
    def name(self) -> str:
        return f"{self.palette_name}/{self.mode}"


def _attrs(**kw) -> str:
    return " ".join(f'{k.replace("_", "-")}="{v}"' for k, v in kw.items() if v is not None)


def render_primitive(pr: dict, style: VStyle, knockout: str | None = None) -> str:
    prim, sec, *_ = style.p
    bg = knockout or style.p[4]
    sw = style.stroke
    if style.mode == "outline":
        paint = dict(fill="none", stroke=prim, stroke_width=sw)
    elif style.mode == "filled":
        paint = (dict(fill=prim, stroke="none") if pr["role"] == "body"
                 else dict(fill="none", stroke=bg, stroke_width=sw))
    else:  # duotone
        paint = (dict(fill=sec, stroke=prim, stroke_width=sw) if pr["role"] == "body"
                 else dict(fill="none", stroke=prim, stroke_width=sw))
    # 'detail' lines in filled style that sit outside the body (handles, steam) must stay visible
    if style.mode == "filled" and pr["role"] == "detail" and pr.get("outside"):
        paint = dict(fill="none", stroke=prim, stroke_width=sw)
    common = dict(stroke_linecap="round", stroke_linejoin="round", transform=pr.get("transform"), **paint)
    t = pr["t"]
    if t == "rect":
        return f'<rect {_attrs(x=pr["x"], y=pr["y"], width=pr["w"], height=pr["h"], rx=pr.get("r", 0), **common)}/>'
    if t == "circle":
        return f'<circle {_attrs(cx=f"{pr["cx"]:.2f}", cy=f"{pr["cy"]:.2f}", r=pr["r"], **common)}/>'
    if t == "ellipse":
        return f'<ellipse {_attrs(cx=pr["cx"], cy=pr["cy"], rx=pr["rx"], ry=pr["ry"], **common)}/>'
    if t == "line":
        common.pop("fill", None)
        if common.get("stroke") == "none":
            common["stroke"] = prim
            common["stroke_width"] = sw
        return f'<line {_attrs(x1=f"{pr["x1"]:.2f}", y1=f"{pr["y1"]:.2f}", x2=f"{pr["x2"]:.2f}", y2=f"{pr["y2"]:.2f}", **common)}/>'
    if t == "poly":
        return f'<polygon {_attrs(points=pr["points"], **common)}/>'
    return f'<path {_attrs(d=pr["d"], **common)}/>'


# Details that stick out of the silhouette; in 'filled' mode they're drawn in the
# primary colour instead of being knocked out.
_OUTSIDE = {
    "briefcase": [1], "calendar": [2, 3], "megaphone": [2], "lock": [0], "solar_panel": [2],
    "wind_turbine": [0], "plant": [0], "suitcase": [0], "palm_tree": [0, 5], "lantern": [0, 3],
    "oil_lamp": [1], "candle": [2], "teacup": [0, 2], "bowl": [2], "chili": [0], "cart": [0],
    "wifi": [0], "search": [1], "graduation_cap": [2], "tree": [2], "bar_chart": [3],
    "lotus": [3], "fireworks": list(range(12)), "sun": list(range(1, 9)), "lightbulb": [1, 2],
}
for _name, _idx in _OUTSIDE.items():
    for _i in _idx:
        ICONS[_name][_i]["outside"] = True


def icon_svg_group(name: str, style: VStyle, x: float, y: float, size: float, knockout: str | None = None) -> str:
    s = size / 64
    inner = "".join(render_primitive(pr, style, knockout) for pr in ICONS[name])
    return f'<g transform="translate({x:.1f} {y:.1f}) scale({s:.4f})">{inner}</g>'


def svg_doc(w: int, h: int, body: str, bg: str, title: str) -> str:
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f"<title>{escape(title)}</title>"
            f'<rect width="{w}" height="{h}" fill="{bg}"/>{body}</svg>')


# --------------------------------------------------------------------------- icon sets
def icon_set_svg(set_name: str, style: VStyle) -> tuple[str, list[str]]:
    names = ICON_SETS[set_name]["icons"]
    cols = 4 if len(names) > 9 else 3
    rows = math.ceil(len(names) / cols)
    cell, pad = 300, 70
    w, h = cols * cell + 2 * pad, rows * cell + 2 * pad
    body = []
    for i, n in enumerate(names):
        cx, cy = pad + (i % cols) * cell, pad + (i // cols) * cell
        body.append(icon_svg_group(n, style, cx + 60, cy + 60, 180))
    return svg_doc(w, h, "".join(body), style.p[4], f"{set_name} icon set"), names


# --------------------------------------------------------------------------- patterns
def _motif(kind: str, rng: random.Random, style: VStyle, T: int) -> list[tuple[float, float, str]]:
    """Return (x, y, svg-fragment-at-origin) elements for one tile."""
    prim, sec, acc, dark, _ = style.p
    els: list[tuple[float, float, str]] = []
    if kind == "dots":
        r1, r2 = rng.uniform(10, 18), rng.uniform(4, 8)
        for (x, y) in [(0, 0), (T / 2, T / 2)]:
            els.append((x, y, f'<circle r="{r1:.1f}" fill="{prim}"/>'))
        for (x, y) in [(T / 2, 0), (0, T / 2)]:
            els.append((x, y, f'<circle r="{r2:.1f}" fill="{acc}"/>'))
    elif kind == "scales":
        r = T / 4
        for i in range(3):
            for j in range(5):
                x = i * T / 2 + (T / 4 if j % 2 else 0)
                y = j * T / 4
                els.append((x, y, f'<circle r="{r:.1f}" fill="{sec if (i + j) % 2 else prim}" stroke="{style.p[4]}" stroke-width="4"/>'))
    elif kind == "waves":
        amp, n = rng.uniform(30, 50), rng.choice([3, 4])
        for k in range(n):
            y0 = k * T / n
            d = f"M{-T / 2:.1f} 0 " + " ".join(
                f"Q{-T / 2 + T / 4 + i * T / 2:.1f} {(-amp if i % 2 == 0 else amp):.1f} {-T / 2 + (i + 1) * T / 2:.1f} 0"
                for i in range(4))
            colour = [prim, acc, dark][k % 3]
            els.append((0, y0, f'<path d="{d}" fill="none" stroke="{colour}" stroke-width="{rng.uniform(5, 9):.1f}" stroke-linecap="round"/>'))
    elif kind == "chevron":
        h = T / 4
        for k in range(4):
            d = f"M0 {h} L{T / 2} 0 L{T} {h}"
            els.append((0, k * h, f'<path d="{d}" fill="none" stroke="{[prim, acc][k % 2]}" stroke-width="{h * 0.35:.1f}" stroke-linejoin="miter"/>'))
    elif kind in ("lotus", "leaves", "lanterns", "stars"):
        icon = {"lotus": "lotus", "leaves": "leaf", "lanterns": "lantern", "stars": "star"}[kind]
        s = rng.uniform(0.42, 0.55) * T
        for (x, y, rot, col) in [(T * 0.25, T * 0.25, 0, prim), (T * 0.75, T * 0.75, 0 if kind == "lanterns" else rng.choice([0, 15, -15, 180]), acc)]:
            st = VStyle(style.palette_name, "filled")
            frag = "".join(render_primitive({**pr, "outside": True} if pr["role"] == "detail" else pr,
                                            VStyle(style.palette_name, "filled"), None)
                           for pr in ICONS[icon])
            frag = frag.replace(st.p[0], col)
            els.append((x, y, f'<g transform="rotate({rot}) scale({s / 64:.4f}) translate(-32 -32)">{frag}</g>'))
        for (x, y) in [(T * 0.75, T * 0.25), (T * 0.25, T * 0.75)]:
            els.append((x, y, f'<circle r="{T * 0.03:.1f}" fill="{dark}"/>'))
    elif kind == "kolam":
        g = 4
        step = T / g
        for i in range(g):
            for j in range(g):
                els.append((i * step + step / 2, j * step + step / 2, f'<circle r="{step * 0.07:.1f}" fill="{dark}"/>'))
        for i in range(g):
            for j in range(g):
                if (i + j) % 2 == 0:
                    cx, cy = i * step + step / 2, j * step + step / 2
                    r = step * 0.92
                    els.append((cx, cy, f'<rect x="{-r / 2:.1f}" y="{-r / 2:.1f}" width="{r:.1f}" height="{r:.1f}" rx="{r * 0.22:.1f}" fill="none" stroke="{prim}" stroke-width="{step * 0.07:.1f}" transform="rotate(45)"/>'))
                else:
                    cx, cy = i * step + step / 2, j * step + step / 2
                    els.append((cx, cy, f'<circle r="{step * 0.2:.1f}" fill="none" stroke="{acc}" stroke-width="{step * 0.05:.1f}"/>'))
    else:
        raise ValueError(f"unknown pattern kind {kind}")
    return els


PATTERN_KINDS = ["dots", "scales", "waves", "chevron", "lotus", "leaves", "lanterns", "stars", "kolam"]


def pattern_tile_svg(kind: str, style: VStyle, seed: int, T: int = 400) -> str:
    """Seamless tile: every element is drawn at all 9 wrap offsets, then clipped to the tile."""
    rng = random.Random(seed)
    els = _motif(kind, rng, style, T)
    bg = style.p[1] if style.mode == "duotone" else style.p[4]
    parts = []
    for (x, y, frag) in els:
        for dx in (-T, 0, T):
            for dy in (-T, 0, T):
                parts.append(f'<g transform="translate({x + dx:.1f} {y + dy:.1f})">{frag}</g>')
    return (f'<clipPath id="tile-clip"><rect width="{T}" height="{T}"/></clipPath>'
            f'<g id="tile"><rect width="{T}" height="{T}" fill="{bg}"/>'
            f'<g clip-path="url(#tile-clip)">{"".join(parts)}</g></g>')


def pattern_sheet_svg(kind: str, style: VStyle, seed: int, repeats: int = 4, T: int = 400) -> str:
    tile = pattern_tile_svg(kind, style, seed, T)
    uses = "".join(f'<use href="#tile" x="{i * T}" y="{j * T}"/>'
                   for i in range(repeats) for j in range(repeats) if (i, j) != (0, 0))
    W = T * repeats
    return svg_doc(W, W, f"<defs/>{tile}{uses}", style.p[4], f"{kind} seamless pattern")


# --------------------------------------------------------------------------- infographics
def _text(x, y, s, size, fill, anchor="middle", weight="normal"):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT}" font-size="{size}" fill="{fill}" '
            f'text-anchor="{anchor}" font-weight="{weight}">{escape(s)}</text>')


def infographic_svg(kind: str, style: VStyle, icons: list[str], n: int, seed: int) -> str:
    rng = random.Random(seed)
    prim, sec, acc, dark, bg = style.p
    W, H = 1600, 1000
    body = [_text(W / 2, 110, "INFOGRAPHIC TITLE HERE", 54, dark, weight="bold"),
            _text(W / 2, 165, "Lorem ipsum dolor sit amet, consectetur adipiscing elit", 26, "#6B6B76")]
    icon_style = VStyle(style.palette_name, "filled", stroke=3.5)
    cols = [prim, acc, dark, prim, acc, dark]
    if kind == "steps":
        gap = (W - 200) / n
        y = 470
        body.append(f'<line x1="{100 + gap / 2}" y1="{y}" x2="{W - 100 - gap / 2}" y2="{y}" stroke="{sec}" stroke-width="14" stroke-linecap="round"/>')
        for i in range(n):
            cx = 100 + gap * (i + 0.5)
            c = cols[i % len(cols)]
            body.append(f'<circle cx="{cx:.1f}" cy="{y}" r="88" fill="{c}"/>')
            body.append(icon_svg_group(icons[i % len(icons)], icon_style_on(icon_style, c), cx - 50, y - 50, 100, knockout=c))
            body.append(_text(cx, y + 160, f"STEP {i + 1:02d}", 30, dark, weight="bold"))
            body.append(_text(cx, y + 200, "Lorem ipsum dolor", 22, "#6B6B76"))
            body.append(_text(cx, y + 230, "sit amet elit", 22, "#6B6B76"))
    elif kind == "timeline":
        x = W / 2
        body.append(f'<line x1="{x}" y1="230" x2="{x}" y2="{H - 60}" stroke="{sec}" stroke-width="12" stroke-linecap="round"/>')
        step = (H - 300) / n
        year = 2018 + rng.randint(0, 4)
        for i in range(n):
            y = 260 + step * (i + 0.5)
            c = cols[i % len(cols)]
            body.append(f'<circle cx="{x}" cy="{y:.1f}" r="44" fill="{c}"/>')
            body.append(icon_svg_group(icons[i % len(icons)], icon_style_on(icon_style, c), x - 26, y - 26, 52, knockout=c))
            side = -1 if i % 2 == 0 else 1
            tx = x + side * 90
            anchor = "end" if side < 0 else "start"
            body.append(_text(tx, y - 6, str(year), 34, c, anchor=anchor, weight="bold"))
            year += rng.choice([1, 2])
            body.append(_text(tx, y + 30, "Lorem ipsum dolor sit amet", 22, "#6B6B76", anchor=anchor))
    elif kind == "bars":
        base, left, right = H - 140, 220, W - 160
        body.append(f'<line x1="{left - 30}" y1="{base}" x2="{right}" y2="{base}" stroke="{dark}" stroke-width="4"/>')
        bw = (right - left) / n
        vals = [rng.uniform(0.3, 1.0) for _ in range(n)]
        for i, v in enumerate(vals):
            h = v * 520
            x = left + i * bw + bw * 0.18
            c = cols[i % len(cols)]
            body.append(f'<rect x="{x:.1f}" y="{base - h:.1f}" width="{bw * 0.64:.1f}" height="{h:.1f}" rx="12" fill="{c}"/>')
            body.append(_text(x + bw * 0.32, base - h - 22, f"{int(v * 100)}%", 30, dark, weight="bold"))
            body.append(icon_svg_group(icons[i % len(icons)], icon_style, x + bw * 0.32 - 28, base + 20, 56))
        for k in range(5):
            y = base - k * 130
            body.append(f'<line x1="{left - 30}" y1="{y}" x2="{right}" y2="{y}" stroke="{sec}" stroke-width="2" stroke-dasharray="8 8"/>')
    elif kind == "cycle":
        cx, cy, R = W / 2, 610, 270
        body.append(f'<circle cx="{cx}" cy="{cy}" r="{R}" fill="none" stroke="{sec}" stroke-width="18"/>')
        body.append(_text(cx, cy + 12, "CORE IDEA", 40, dark, weight="bold"))
        for i in range(n):
            a = -math.pi / 2 + 2 * math.pi * i / n
            x, y = cx + R * math.cos(a), cy + R * math.sin(a)
            c = cols[i % len(cols)]
            body.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="72" fill="{c}"/>')
            body.append(icon_svg_group(icons[i % len(icons)], icon_style_on(icon_style, c), x - 40, y - 40, 80, knockout=c))
            side = math.cos(a)
            anchor = "start" if side > 0.2 else "end" if side < -0.2 else "middle"
            lx = x + {"start": 95, "end": -95, "middle": 0}[anchor]
            ly = y + 10 if anchor != "middle" else y + (-95 if math.sin(a) < 0 else 112)
            body.append(_text(lx, ly, f"Option {i + 1:02d}", 28, dark, anchor=anchor, weight="bold"))
    else:
        raise ValueError(kind)
    return svg_doc(W, H, "".join(body), bg, f"{kind} infographic template")


def icon_style_on(base: VStyle, colour: str) -> VStyle:
    """Icons sitting on a coloured disc: white silhouette with coloured knockouts."""
    pal = list(PALETTES[base.palette_name])
    pal[0], pal[4] = "#FFFFFF", colour
    key = f"_on_{colour}"
    PALETTES[key] = pal          # private palettes start with "_" and are never sampled
    return VStyle(key, "filled", base.stroke)


INFOGRAPHIC_KINDS = {"steps": (4, 6), "timeline": (4, 6), "bars": (5, 8), "cycle": (4, 6)}


# --------------------------------------------------------------------------- rendering + registry
def render_outputs(svg: str, out_stem: Path, preview_long_side: int = 5000) -> tuple[Path, Path, Path]:
    import cairosvg

    out_stem.parent.mkdir(parents=True, exist_ok=True)
    svg_path, eps_path, jpg_path = (out_stem.with_suffix(s) for s in (".svg", ".eps", ".jpg"))
    svg_path.write_text(svg)
    cairosvg.svg2eps(bytestring=svg.encode(), write_to=str(eps_path))
    png = cairosvg.svg2png(bytestring=svg.encode(), output_width=None, scale=_scale_for(svg, preview_long_side))
    with Image.open(io.BytesIO(png)) as im:
        im.convert("RGB").save(jpg_path, "JPEG", quality=92)
    return svg_path, eps_path, jpg_path


def _scale_for(svg: str, long_side: int) -> float:
    import re
    m = re.search(r'width="(\d+)" height="(\d+)"', svg)
    w, h = (int(m.group(1)), int(m.group(2))) if m else (1000, 1000)
    return long_side / max(w, h)


def _register(store: Store, svg: str, kind: str, topic: str, style: VStyle, set_id: str, description: str,
              settings: Settings) -> Asset:
    aid = hashlib.sha1(svg.encode()).hexdigest()[:16]
    existing = store.get(aid)
    if existing:
        return existing
    stem = settings.dir(f"assets/code_vectors/{kind}") / aid
    svg_p, eps_p, jpg_p = render_outputs(svg, stem)
    a = Asset(id=aid, path=str(svg_p), preview_path=str(jpg_p), lane=Lane.CODE_VECTORS, topic=topic,
              style=style.name, set_id=set_id, prompt=description, qc={"kind": kind, "eps": str(eps_p)})
    store.upsert(a)
    return a


def make_icon_sets(settings: Settings, store: Store, sets: list[str] | None = None, styles_per_set: int = 1,
                   seed: int | None = None) -> list[Asset]:
    rng = random.Random(seed)
    out = []
    for set_name in sets or list(ICON_SETS):
        palettes = rng.sample([p for p in PALETTES if not p.startswith("_")], styles_per_set)
        for pal in palettes:
            style = VStyle(pal, rng.choice(MODES), stroke=rng.choice([2.5, 3.0, 3.5]))
            svg, names = icon_set_svg(set_name, style)
            desc = (f"{set_name} icon set, {len(names)} {style.mode} vector icons in one consistent style: "
                    + ", ".join(n.replace("_", " ") for n in names))
            out.append(_register(store, svg, "icons", ICON_SETS[set_name]["topic"], style,
                                 f"icons-{set_name}", desc, settings))
    return out


def make_patterns(settings: Settings, store: Store, kinds: list[str] | None = None, count: int = 6,
                  seed: int | None = None) -> list[Asset]:
    rng = random.Random(seed)
    kinds = kinds or PATTERN_KINDS
    topics = {"lotus": "south asian textile and craft patterns", "kolam": "south asian textile and craft patterns",
              "lanterns": "Vesak", "stars": "Christmas", "leaves": "sustainability and renewable energy"}
    out = []
    for i in range(count):
        kind = kinds[i % len(kinds)]
        style = VStyle(rng.choice([p for p in PALETTES if not p.startswith("_")]), rng.choice(["filled", "duotone"]))
        s = rng.randrange(1 << 30)
        svg = pattern_sheet_svg(kind, style, s)
        desc = f"seamless repeating {kind} pattern, vector background tile, {style.palette_name.replace('_', ' ')} colours"
        out.append(_register(store, svg, "patterns", topics.get(kind, "abstract backgrounds and patterns"), style,
                             f"pattern-{kind}", desc, settings))
    return out


def make_infographics(settings: Settings, store: Store, kinds: list[str] | None = None, count: int = 4,
                      seed: int | None = None) -> list[Asset]:
    rng = random.Random(seed)
    kinds = kinds or list(INFOGRAPHIC_KINDS)
    out = []
    for i in range(count):
        kind = kinds[i % len(kinds)]
        set_name = rng.choice(list(ICON_SETS))
        style = VStyle(rng.choice([p for p in PALETTES if not p.startswith("_")]), "filled")
        lo, hi = INFOGRAPHIC_KINDS[kind]
        n = rng.randint(lo, hi)
        svg = infographic_svg(kind, style, ICON_SETS[set_name]["icons"], n, rng.randrange(1 << 30))
        desc = f"{kind} infographic template with {n} options, editable vector, {set_name} icons, placeholder text"
        out.append(_register(store, svg, "infographics", ICON_SETS[set_name]["topic"], style,
                             f"infographic-{kind}", desc, settings))
    return out
