"""
driftchart - pure-Python SVG renderer for stepped drift diagrams.

No dependencies. The same SVG is used for the on-screen preview (the browser
only adds hover/legend interaction) and for file export, so what you see is
exactly what you save.

Layout follows the reference figure: floors on the vertical axis, drift on the
horizontal axis, one stepped polyline per curve, vertical red limit line with
a "Limit" label, legend outside the plot area.
"""

from __future__ import annotations

import html
import math
from typing import Any, Sequence

from driftcore import fmt_num, fmt_limit, nice_ticks

DASHES = {
    "solid": "",
    "dash": "8 5",
    "dot": "2 4",
    "dashdot": "10 4 2 4",
    "longdash": "14 6",
}

FONT = "Segoe UI, Arial, Helvetica, sans-serif"

LABELS = {
    "el": {
        "x_ratio": "Σχετική μετακίνηση ορόφου  d  [–]",
        "x_percent": "Σχετική μετακίνηση ορόφου  d  [%]",
        "y_floor": "Όροφος",
        "y_elevation": "Υψόμετρο  z  [m]",
        "limit": "Limit",
        "mean": "Μέση καμπύλη",
        "no_data": "Δεν υπάρχουν δεδομένα για εμφάνιση",
    },
    "en": {
        "x_ratio": "Storey drift  d  [–]",
        "x_percent": "Storey drift  d  [%]",
        "y_floor": "Storey",
        "y_elevation": "Elevation  z  [m]",
        "limit": "Limit",
        "mean": "Mean curve",
        "no_data": "No data to display",
    },
}


def labels(lang: str | None) -> dict[str, str]:
    return LABELS["en"] if str(lang or "el").lower().startswith("en") else LABELS["el"]


def _esc(text: Any) -> str:
    return html.escape("" if text is None else str(text), quote=True)


def _dash(dash: str) -> str:
    return DASHES.get(dash or "solid", "")


def _tick_label(value: float, x_mode: str, lang: str = "el") -> str:
    comma = not str(lang).lower().startswith("en")
    if x_mode == "percent":
        return fmt_num(value * 100.0, 3, comma=comma).rstrip("0").rstrip("," if comma else ".") + "%"
    s = fmt_num(value, 5, comma=comma)
    sep = "," if comma else "."
    if sep in s:
        s = s.rstrip("0").rstrip(sep)
    return s


def _y_label(value: float, y_mode: str, lang: str = "el") -> str:
    comma = not str(lang).lower().startswith("en")
    if y_mode == "elevation":
        s = fmt_num(value, 2, comma=comma)
        return s.rstrip("0").rstrip("," if comma else ".")
    return fmt_num(value, 0, comma=comma)


def _text(x, y, txt, size=11, anchor="start", fill="#333", weight="normal",
          rotate=None, family=FONT, opacity=None, style=None):
    tr = f' transform="rotate({rotate} {x} {y})"' if rotate is not None else ""
    op = f' opacity="{opacity}"' if opacity is not None else ""
    st = f' font-style="{style}"' if style else ""
    return (f'<text x="{x:.2f}" y="{y:.2f}" font-family="{family}" font-size="{size}" '
            f'fill="{fill}" text-anchor="{anchor}" font-weight="{weight}"{op}{st}{tr}>'
            f'{_esc(txt)}</text>')


def _range(payload: dict[str, Any], x_min, x_max) -> tuple[float, float]:
    values = []
    for s in payload.get("series", []):
        if not s.get("visible", True):
            continue
        for p in s["result"].get("points", []):
            values.append(p["x"])
    mean = payload.get("mean")
    if mean:
        values.extend(p["x"] for p in mean.get("points", []))
    data_max = max(values) if values else 0.0
    limit = payload.get("diagram", {}).get("limit")
    hi = data_max
    if x_max is not None:
        hi = float(x_max)
    else:
        if limit is not None and limit > 0:
            if hi <= 0 or limit <= hi * 2.5:
                hi = max(hi, limit)
        hi = hi * 1.12 if hi > 0 else 0.003
        ticks = nice_ticks(0, hi, 5)
        if len(ticks) > 1:
            step = ticks[1] - ticks[0]
            while ticks[-1] < hi - 1e-12 and len(ticks) < 40:
                ticks.append(round(ticks[-1] + step, 12))
        hi = ticks[-1] if ticks else hi
    lo = 0.0 if x_min is None else float(x_min)
    if hi <= lo:
        hi = lo + 0.001
    return lo, hi


def render_svg(
    payload: dict[str, Any],
    *,
    width: int = 940,
    height: int = 620,
    title: str | None = None,
    subtitle: str | None = None,
    x_mode: str = "ratio",
    y_mode: str = "floor",
    show_grid: bool = True,
    legend_outside: bool = True,
    x_min=None,
    x_max=None,
    note: str = "",
    transparent: bool = False,
    include_hover: bool = True,
    lang: str = "el",
) -> str:
    L = labels(lang)
    comma = not str(lang or "el").lower().startswith("en")
    diagram = payload.get("diagram", {})
    series = [s for s in payload.get("series", []) if s.get("visible", True)]
    mean = payload.get("mean")
    title = title if title is not None else diagram.get("name", "")
    if x_mode is None:
        x_mode = diagram.get("x_mode", "ratio")
    y_mode = y_mode or diagram.get("y_mode", "floor")
    show_grid = diagram.get("show_grid", True) if show_grid is None else show_grid

    # geometry ---------------------------------------------------------
    m_left, m_top, m_bottom = 74, 58, 62
    x_lo, x_hi = _range(payload, x_min, x_max)
    ys: list[float] = []
    for s in series:
        ys.extend(p["y"] for p in s["result"].get("points", []))
    if mean:
        ys.extend(p["y"] for p in mean.get("points", []))
    if y_mode == "elevation":
        y_lo = 0.0
        y_hi = (max(ys) if ys else 1.0) * 1.04
    else:
        y_lo = 0.0
        y_hi = max(ys) if ys else 1.0
        y_hi = max(y_hi, 1.0) * 1.02

    legend_items = [{"id": s.get("id", ""), "name": s["name"],
                     "color": s.get("color", "#333"), "dash": s.get("dash", "solid"),
                     "width": s.get("width", 2.0)} for s in series]
    if mean:
        legend_items.append({"id": "__mean__", "name": L["mean"],
                             "color": "#000000", "dash": "dash", "width": 2.0})
    legend_cols = 1
    if legend_outside:
        legend_cols = 1 if len(legend_items) <= 18 else 2
    m_right = 34
    if legend_outside:
        m_right = 24 + legend_cols * 190
    # not enough room for an outside legend? keep it inside the axes
    if width - m_left - m_right < 300:
        legend_outside = False
        m_right = 34

    plot_left = m_left
    plot_right = width - m_right
    plot_top = m_top
    plot_bottom = height - m_bottom
    if plot_right - plot_left < 120:
        plot_right = plot_left + 120

    def sx(v: float) -> float:
        return plot_left + (v - x_lo) / (x_hi - x_lo) * (plot_right - plot_left)

    def sy(v: float) -> float:
        return plot_bottom - (v - y_lo) / (y_hi - y_lo) * (plot_bottom - plot_top)

    out: list[str] = []
    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
               f'height="{height}" viewBox="0 0 {width} {height}" '
               f'font-family="{FONT}">')
    if not transparent:
        out.append(f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>')

    # title
    ty = 26
    if title:
        out.append(_text(m_left, ty, title, size=15, weight="600", fill="#1a1a1a"))
        ty += 18
    if subtitle:
        out.append(_text(m_left, ty if title else 22, subtitle, size=11, fill="#666"))

    # grid + ticks -----------------------------------------------------
    x_ticks = nice_ticks(x_lo, x_hi, 6)
    if y_mode == "elevation":
        y_ticks = nice_ticks(y_lo, y_hi, 6)
    else:
        span = y_hi - y_lo
        step = 1
        for cand in (1, 2, 5, 10, 20, 50, 100):
            if span / cand <= 22:
                step = cand
                break
        y_ticks = [float(i) for i in range(int(math.floor(y_lo)), int(math.ceil(y_hi)) + 1, step)]

    grid_parts = ['<g class="grid" stroke="#e3e6ea" stroke-width="1">']
    for t in x_ticks:
        x = sx(t)
        if show_grid:
            grid_parts.append(f'<line x1="{x:.2f}" y1="{plot_top}" x2="{x:.2f}" y2="{plot_bottom}"/>')
    for t in y_ticks:
        y = sy(t)
        if show_grid:
            grid_parts.append(f'<line x1="{plot_left}" y1="{y:.2f}" x2="{plot_right}" y2="{y:.2f}"/>')
    grid_parts.append('</g>')
    out.extend(grid_parts)

    # axes -------------------------------------------------------------
    out.append(f'<g stroke="#4a4a4a" stroke-width="1.1" fill="none">'
               f'<line x1="{plot_left}" y1="{plot_bottom}" x2="{plot_right}" y2="{plot_bottom}"/>'
               f'<line x1="{plot_left}" y1="{plot_top}" x2="{plot_left}" y2="{plot_bottom}"/>'
               f'</g>')
    for t in x_ticks:
        x = sx(t)
        out.append(f'<line x1="{x:.2f}" y1="{plot_bottom}" x2="{x:.2f}" '
                   f'y2="{plot_bottom + 5}" stroke="#4a4a4a" stroke-width="1"/>')
        out.append(_text(x, plot_bottom + 18, _tick_label(t, x_mode), size=10,
                         anchor="middle", fill="#444"))
    for t in y_ticks:
        y = sy(t)
        out.append(f'<line x1="{plot_left - 5}" y1="{y:.2f}" x2="{plot_left}" '
                   f'y2="{y:.2f}" stroke="#4a4a4a" stroke-width="1"/>')
        out.append(_text(plot_left - 9, y + 3.5, _y_label(t, y_mode), size=10,
                         anchor="end", fill="#444"))

    x_axis_label = L["x_percent"] if x_mode == "percent" else L["x_ratio"]
    out.append(_text((plot_left + plot_right) / 2, height - 14, x_axis_label,
                     size=11.5, anchor="middle", fill="#222"))
    y_axis_label = L["y_elevation"] if y_mode == "elevation" else L["y_floor"]
    out.append(_text(20, (plot_top + plot_bottom) / 2, y_axis_label, size=11.5,
                     anchor="middle", fill="#222", rotate=-90))

    # limit line -------------------------------------------------------
    limit = diagram.get("limit")
    if limit is not None and limit > 0:
        lx = sx(limit)
        if plot_left - 1 <= lx <= plot_right + 1:
            out.append(f'<line x1="{lx:.2f}" y1="{plot_top}" x2="{lx:.2f}" '
                       f'y2="{plot_bottom}" stroke="#d32020" stroke-width="2" '
                       f'stroke-dasharray="7 4" class="limit-line"/>')
            label = f"{L['limit']} {fmt_num(limit, 5, comma=comma)}"
            tw = 7.2 * len(label) + 10
            ly = plot_top + 4
            out.append(f'<rect x="{lx - tw - 5:.2f}" y="{ly - 11}" width="{tw:.1f}" '
                       f'height="16" fill="#ffffff" opacity="0.85"/>')
            out.append(_text(lx - 7, ly + 1, label, size=10, anchor="end",
                             fill="#d32020", weight="600"))

    # curves -----------------------------------------------------------
    clip_id = "plotclip"
    out.append(f'<defs><clipPath id="{clip_id}"><rect x="{plot_left}" y="{plot_top - 2}" '
               f'width="{plot_right - plot_left}" height="{plot_bottom - plot_top + 4}"/>'
               f'</clipPath></defs>')
    out.append(f'<g clip-path="url(#{clip_id})">')
    for s in series:
        color = s.get("color") or "#1f4e79"
        width_px = float(s.get("width") or 2.0)
        dash = _dash(s.get("dash", "solid"))
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        sid = s.get("id", "")
        out.append(f'<g class="curve" data-curve-id="{_esc(sid)}" '
                   f'data-name="{_esc(s.get("name", ""))}">')
        for seg in s["result"].get("segments", []):
            if len(seg) < 2:
                continue
            d = "M " + " L ".join(f"{sx(p['x']):.2f} {sy(p['y']):.2f}" for p in seg)
            out.append(f'<path d="{d}" fill="none" stroke="{color}" '
                       f'stroke-width="{width_px}" stroke-linejoin="miter" '
                       f'stroke-linecap="butt"{dash_attr}/>')
        out.append('</g>')
    if mean and mean.get("segments"):
        out.append(f'<g class="curve mean" data-name="{_esc(L["mean"])}">')
        for seg in mean["segments"]:
            if len(seg) < 2:
                continue
            d = "M " + " L ".join(f"{sx(p['x']):.2f} {sy(p['y']):.2f}" for p in seg)
            out.append(f'<path d="{d}" fill="none" stroke="#111111" stroke-width="2.2" '
                       f'stroke-dasharray="12 5"/>')
        out.append('</g>')
    out.append('</g>')

    # hover targets ----------------------------------------------------
    if include_hover:
        out.append('<g class="hover-layer" fill="transparent">')
        for s in series:
            color = s.get("color") or "#1f4e79"
            for p in s["result"].get("points", []):
                x, y = sx(p["x"]), sy(p["y"])
                out.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="7" '
                           f'data-curve="{_esc(s.get("name", ""))}" '
                           f'data-color="{_esc(color)}" data-x="{p["x"]:.10g}" '
                           f'data-y="{p["y"]:.10g}" data-floor="{p["floor"]:.10g}" '
                           f'data-phase="{p["phase"]}"/>')
        out.append('</g>')

    # legend -----------------------------------------------------------
    if legend_outside and legend_items:
        rows_per_col = min(len(legend_items), 18)
        col_w = 190
        base_x = plot_right + 26
        base_y = plot_top + 6
        for i, item in enumerate(legend_items):
            col = i // rows_per_col
            row = i % rows_per_col
            x = base_x + col * col_w
            y = base_y + row * 20
            name = item["name"]
            color = item["color"]
            lw = item["width"]
            dash_attr = f' stroke-dasharray="{_dash(item["dash"])}"' if _dash(item["dash"]) else ""
            tr = f' class="legend" data-curve-id="{_esc(item["id"])}" data-name="{_esc(name)}"'
            out.append(f'<g{tr}>')
            out.append(f'<line x1="{x}" y1="{y}" x2="{x + 26}" y2="{y}" '
                       f'stroke="{color}" stroke-width="{lw}"{dash_attr}/>')
            label = name if len(name) <= 22 else name[:21] + "…"
            out.append(_text(x + 32, y + 4, label, size=10.5, fill="#222"))
            out.append('</g>')
    elif legend_items:
        # inside legend, top-right of plot
        lw = max((len(it["name"]) for it in legend_items), default=8)
        box_w = 40 + lw * 6.4
        x0 = plot_right - box_w - 8
        y0 = plot_top + 8
        out.append(f'<rect x="{x0:.1f}" y="{y0}" width="{box_w:.1f}" '
                   f'height="{len(legend_items) * 18 + 10}" fill="#ffffff" '
                   f'fill-opacity="0.9" stroke="#cccccc"/>')
        for i, item in enumerate(legend_items):
            y = y0 + 18 + i * 18
            dash_attr = f' stroke-dasharray="{_dash(item["dash"])}"' if _dash(item["dash"]) else ""
            out.append(f'<line x1="{x0 + 10}" y1="{y - 4}" x2="{x0 + 34}" y2="{y - 4}" '
                       f'stroke="{item["color"]}" stroke-width="{item["width"]}"{dash_attr}/>')
            out.append(_text(x0 + 40, y, item["name"], size=10.5, fill="#222"))

    # footnote / emptiness ---------------------------------------------
    if not series:
        out.append(_text((plot_left + plot_right) / 2, (plot_top + plot_bottom) / 2,
                         "Δεν υπάρχουν δεδομένα για εμφάνιση", size=13,
                         anchor="middle", fill="#9a9a9a"))
    if note:
        out.append(_text(m_left, height - 2, note, size=9.5, fill="#777"))

    out.append('</svg>')
    return "\n".join(out)


def payload_issues(payload: dict[str, Any], lang: str = "el") -> list[str]:
    """Short, human readable list of things that block or distort the plot."""
    en = str(lang or "el").lower().startswith("en")
    notes = []
    if payload.get("spectral_warning"):
        notes.append("A response-spectrum curve is present - see the warning."
                     if en else
                     "Υπάρχει καμπύλη φασματικής ανάλυσης - βλ. προειδοποίηση.")
    unknown_base = any(i.get("code") == "NO_BASE" for i in payload.get("issues", []))
    if unknown_base:
        notes.append("The base is missing: no drift was plotted."
                     if en else
                     "Λείπει η βάση: δεν σχεδιάστηκε drift.")
    return notes
