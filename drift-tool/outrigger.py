"""
outrigger - optimization of outrigger location.

Implements the equations of the user's study (single outrigger level).
All computations are deterministic; no third-party dependencies.
"""
from __future__ import annotations

import math
from typing import Any, Sequence

from driftcore import fmt_num


def _f(x: float, omega: float) -> float:
    # F = (1 - x^2 - x^3 + x^5)/(1 - x + omega)  (= reduction, up to constants)
    num = 1.0 - x * x - x ** 3 + x ** 5
    den = 1.0 - x + omega
    if den == 0:
        return 0.0
    return num / den


def _g(x: float, omega: float) -> float:
    # numerator of derivative: N'*(1-x+omega) + N
    n = 1.0 - x * x - x ** 3 + x ** 5
    np_ = -2.0 * x - 3.0 * x * x + 5.0 * x ** 4
    d = 1.0 - x + omega
    return np_ * d + n


def solve_optimal_xbar(omega: float) -> float:
    """Solve dF/dx = 0 in (0,1) and return the x that maximises F."""
    omega = float(omega)
    # scan for sign changes of g
    N = 2000
    xs = [i / N for i in range(1, N)]  # 0 < x < 1
    roots: list[float] = []
    prev_x = xs[0]
    prev_g = _g(prev_x, omega)
    for x in xs[1:]:
        gx = _g(x, omega)
        if prev_g == 0:
            roots.append(prev_x)
        if prev_g * gx < 0:
            # bisection
            lo, hi = prev_x, x
            for _ in range(80):
                mid = (lo + hi) / 2.0
                if _g(lo, omega) * _g(mid, omega) <= 0:
                    hi = mid
                else:
                    lo = mid
            roots.append((lo + hi) / 2.0)
        prev_x = x
        prev_g = gx

    # choose root with maximum F
    if not roots:
        # fallback: sample
        best_x = 0.5
        best_f = _f(0.5, omega)
        for i in range(1, N):
            x = i / N
            fv = _f(x, omega)
            if fv > best_f:
                best_f = fv
                best_x = x
        return best_x

    best_x = roots[0]
    best_f = _f(best_x, omega)
    for r in roots[1:]:
        fv = _f(r, omega)
        if fv > best_f:
            best_f = fv
            best_x = r
    # also check a fine local refinement around best_x
    return float(min(max(best_x, 1e-9), 1 - 1e-9))


def compute_ga(system: str, params: dict[str, Any]) -> dict[str, Any]:
    """Compute delta_s and GA_o for CSB or BIE."""
    E = float(params.get("E") or 0.0)
    d = float(params.get("d") or 0.0)
    a = float(params.get("a") or 0.0)
    h = float(params.get("h") or 0.0)
    Ad = float(params.get("A_d") or 0.0)
    Ab = float(params.get("A_b") or 0.0)
    e_over_r = float(params.get("e_over_r") or 0.0)
    Q = 1.0  # cancels

    if system == "BIE":
        # eq (4)
        term1 = Q * (2.0 * d * d / (a * a)) * ((1.0 + e_over_r * e_over_r) / (E * Ad / d)) if (a and Ad and E) else 0.0
        term2 = (Q / E) * (a / (4.0 * Ab)) if (E and Ab) else 0.0
        delta_s = term1 + term2
    else:
        # eq (2)
        if E == 0 or a == 0 or Ad == 0:
            delta_s = 0.0
        else:
            delta_s = (Q / E) * (2.0 * d ** 3 / (a * a * Ad) + a / (4.0 * Ab))
    GA_o = (Q * h / delta_s) if delta_s not in (0, None) else 0.0
    # eq (3) K_e (informational) for BIE
    K_e = None
    if system == "BIE":
        # K_e = (E*A/L)/(1+(e/r)^2) -- A,L not supplied; report None
        K_e = None
    return {"delta_s": delta_s, "GA_o": GA_o, "K_e": K_e}


def compute_sh_sv(params: dict[str, Any], GA_o: float) -> dict[str, float]:
    alpha = float(params.get("alpha") or 0.0)
    b = float(params.get("b") or 0.0)
    EI_o = float(params.get("EI_o") or 0.0)
    h = float(params.get("h") or 0.0)
    H = float(params.get("H") or 0.0)
    EI_w = float(params.get("EI_w") or 0.0)
    EI_c = float(params.get("EI_c") or 0.0)

    if alpha == 0:
        S_h = 0.0
    else:
        term = 0.0
        if EI_o:
            term += b / (24.0 * EI_o)
        if GA_o and h:
            term += 1.0 / (h * GA_o)
        S_h = (1.0 / (alpha * alpha)) * term
    S_v = 0.0
    if EI_w:
        S_v += H / EI_w
    if EI_c:
        S_v += H / EI_c
    omega = (S_h / S_v) if S_v else 0.0
    return {"S_h": S_h, "S_v": S_v, "omega": omega}


def top_displacement(H, X, w, EI_w, S_v, S_h) -> float:
    H = float(H); X = float(X); w = float(w); EI_w = float(EI_w)
    if EI_w == 0:
        return 0.0
    y0 = w * H ** 4 / (8.0 * EI_w)
    denom = (1.0 - X) * S_v + S_h
    if denom == 0:
        return y0
    Mr = w * H ** 3 * (1.0 - X ** 3) / (6.0 * EI_w * denom)
    y_red = Mr * (H * H * (1.0 - X * X)) / (2.0 * EI_w)
    return y0 - y_red


def nearest_floor(z: float, heights: Sequence[float]) -> dict[str, Any]:
    cum: list[tuple[int, float]] = []
    s = 0.0
    for i, h in enumerate(heights, start=1):
        s += float(h)
        cum.append((i, s))
    if not cum:
        return {"storey": None, "level": None, "deviation": None, "neighbors": []}
    best = min(cum, key=lambda t: abs(t[1] - z))
    idx = best[0]
    neighbors = []
    if idx > 1:
        neighbors.append(cum[idx - 2])
    if idx < len(cum):
        neighbors.append(cum[idx])
    return {
        "storey": idx,
        "level": best[1],
        "deviation": best[1] - z,
        "neighbors": [{"storey": i, "level": lvl} for (i, lvl) in neighbors],
    }


def parse_heights(text: str) -> list[float]:
    out: list[float] = []
    for part in str(text or "").replace(",", " ").replace(";", " ").replace("\t", " ").split():
        try:
            out.append(float(part))
        except ValueError:
            continue
    # also handle one-per-line already covered by split
    return out


def compute_all(params: dict[str, Any]) -> dict[str, Any]:
    system = params.get("system", "CSB")
    # GA_o: use provided if present, else auto
    GA_provided = params.get("GA_o")
    auto = params.get("auto_ga", True)
    if auto or GA_provided is None or str(GA_provided).strip() == "":
        ga = compute_ga(system, params)
        delta_s = ga["delta_s"]
        GA_o = ga["GA_o"]
    else:
        delta_s = None
        GA_o = float(GA_provided)

    params2 = dict(params)
    params2["GA_o"] = GA_o
    shsv = compute_sh_sv(params2, GA_o)
    S_h = shsv["S_h"]; S_v = shsv["S_v"]; omega = shsv["omega"]

    H = float(params.get("H") or 0.0)
    w = float(params.get("w") or 1.0)
    EI_w = float(params.get("EI_w") or 0.0)
    xbar_opt = solve_optimal_xbar(omega)
    x = xbar_opt * H
    z = H - x
    y_top_opt = top_displacement(H, xbar_opt, w, EI_w, S_v, S_h)

    # chart 1 data
    omegas = [i / 100.0 for i in range(0, 101)]
    chart1 = [(om, solve_optimal_xbar(om)) for om in omegas]

    # chart 2 data
    eccs = params.get("eccentricities") or [0, 1.52, 2.13, 2.85, 3.80, 4.75]
    curves2 = []
    xs = [i / 50.0 for i in range(0, 51)]
    for er in eccs:
        p = dict(params)
        p["e_over_r"] = er
        p["system"] = "BIE" if er and float(er) != 0 else "CSB"
        # recompute GA_o for this eccentricity
        if auto or GA_provided is None or str(GA_provided).strip() == "":
            ga2 = compute_ga(p["system"], p)
            GA2 = ga2["GA_o"]
        else:
            GA2 = float(GA_provided)
        p["GA_o"] = GA2
        shsv2 = compute_sh_sv(p, GA2)
        S_h2 = shsv2["S_h"]; S_v2 = shsv2["S_v"]
        pts = []
        for X in xs:
            y = top_displacement(H, X, w, EI_w, S_v2, S_h2)
            pts.append((X, y))
        # optimal for this curve
        om2 = shsv2["omega"]
        xbar2 = solve_optimal_xbar(om2)
        curves2.append({
            "e_over_r": er,
            "omega": om2,
            "GA_o": GA2,
            "S_h": S_h2,
            "S_v": S_v2,
            "optimal_xbar": xbar2,
            "points": pts,
        })

    # floor conversion
    heights = params.get("floor_heights") or []
    if isinstance(heights, str):
        heights = parse_heights(heights)
    floor_info = nearest_floor(z, heights)

    return {
        "system": system,
        "delta_s": delta_s,
        "GA_o": GA_o,
        "S_h": S_h,
        "S_v": S_v,
        "omega": omega,
        "xbar_opt": xbar_opt,
        "x": x,
        "z": z,
        "y_top_opt": y_top_opt,
        "chart1": chart1,
        "chart2": curves2,
        "floor_info": floor_info,
        "H": H,
    }


def render_chart1(data: dict[str, Any], width: int = 720, height: int = 420, lang: str = "el") -> str:
    chart1 = data["chart1"]
    comma = not str(lang).lower().startswith("en")
    # x-axis omega 0..1, y-axis xbar (inverted: 0 at top? requirement: smaller values top)
    # We'll plot xbar on vertical, omega horizontal. Invert y so small xbar top.
    margin = 60
    pl, pr = margin, width - margin
    pt, pb = 40, height - 50
    def sx(v):
        return pl + v * (pr - pl)
    def sy(v):
        # v in [0,1], 0 at top
        return pt + v * (pb - pt)
    # note: invert: smaller xbar -> smaller v? requirement smaller values top. xbar small -> top. So y = pt + xbar*(pb-pt) would put small top? if xbar=0 top, xbar=1 bottom. yes.
    out = []
    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">')
    out.append(f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>')
    # axes
    out.append(f'<line x1="{pl}" y1="{pt}" x2="{pl}" y2="{pb}" stroke="#333"/>')
    out.append(f'<line x1="{pl}" y1="{pb}" x2="{pr}" y2="{pb}" stroke="#333"/>')
    # ticks x
    for i in range(0, 11):
        v = i / 10.0
        x = sx(v)
        out.append(f'<line x1="{x:.1f}" y1="{pb}" x2="{x:.1f}" y2="{pb+5}" stroke="#333"/>')
        out.append(f'<text x="{x:.1f}" y="{pb+18}" font-size="10" text-anchor="middle">{fmt_num(v,1,comma=comma)}</text>')
    # ticks y
    for i in range(0, 11):
        v = i / 10.0
        y = sy(v)
        out.append(f'<line x1="{pl-5}" y1="{y:.1f}" x2="{pl}" y2="{y:.1f}" stroke="#333"/>')
        out.append(f'<text x="{pl-8}" y="{y+3:.1f}" font-size="10" text-anchor="end">{fmt_num(1-v,1,comma=comma)}</text>')
    # curve
    pts = " ".join(f"{sx(om):.1f},{sy(xb):.1f}" for om, xb in chart1)
    out.append(f'<polyline points="{pts}" fill="none" stroke="#1f4e79" stroke-width="2"/>')
    # user point
    om_u = data["omega"]; xb_u = data["xbar_opt"]
    out.append(f'<circle cx="{sx(om_u):.1f}" cy="{sy(xb_u):.1f}" r="5" fill="#c00000"/>')
    out.append(f'<text x="{sx(om_u)+8:.1f}" y="{sy(xb_u)-8:.1f}" font-size="10" fill="#c00000">ω={fmt_num(om_u,3,comma=comma)}, x/H={fmt_num(xb_u,3,comma=comma)}</text>')
    # labels
    out.append(f'<text x="{(pl+pr)/2:.1f}" y="{height-12}" font-size="12" text-anchor="middle">ω = S_h/S_v</text>')
    out.append(f'<text x="18" y="{(pt+pb)/2:.1f}" font-size="12" text-anchor="middle" transform="rotate(-90 18 {(pt+pb)/2:.1f})">x/H</text>')
    out.append('</svg>')
    return "\n".join(out)


def render_chart2(data: dict[str, Any], width: int = 720, height: int = 420, lang: str = "el") -> str:
    comma = not str(lang).lower().startswith("en")
    curves = data["chart2"]
    # x-axis: top displacement (m), y-axis: x/H (inverted? vertical x/H). We'll plot x/H vertical 0 top? 
    # Requirement: vertical x/H. Use 0 at top? Figure likely x/H from 0 to1 top to bottom? We'll do small top.
    all_y = [p[1] for c in curves for p in c["points"]]
    all_x = [p[0] for c in curves for p in c["points"]]
    xmin = min(all_x) if all_x else 0.0
    xmax = max(all_x) if all_x else 1.0
    if xmax <= xmin:
        xmax = xmin + 1.0
    margin = 60
    pl, pr = margin, width - margin - 140  # room for legend
    pt, pb = 40, height - 50
    def sx(v):
        return pl + (v - xmin) / (xmax - xmin) * (pr - pl)
    def sy(v):
        return pt + v * (pb - pt)
    palette = ["#1f4e79", "#c00000", "#2e7d32", "#ed7d31", "#7030a0", "#00838f"]
    out = []
    out.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">')
    out.append(f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>')
    out.append(f'<line x1="{pl}" y1="{pt}" x2="{pl}" y2="{pb}" stroke="#333"/>')
    out.append(f'<line x1="{pl}" y1="{pb}" x2="{pr}" y2="{pb}" stroke="#333"/>')
    # curve polylines
    for ci, c in enumerate(curves):
        color = palette[ci % len(palette)]
        pts = " ".join(f"{sx(p[0]):.1f},{sy(p[1]):.1f}" for p in c["points"])
        out.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2"/>')
        # optimal marker
        opt_x = c["optimal_xbar"]
        # find y at optimal
        opt_y = None
        if c["points"]:
            nearest = min(c["points"], key=lambda p: abs(p[1] - opt_x))
            opt_y = nearest[0]
        if opt_y is not None:
            out.append(f'<circle cx="{sx(opt_y):.1f}" cy="{sy(opt_x):.1f}" r="4" fill="{color}"/>')
    # legend
    lx = pr + 15
    ly = pt
    for ci, c in enumerate(curves):
        color = palette[ci % len(palette)]
        y = ly + ci * 18
        out.append(f'<line x1="{lx}" y1="{y}" x2="{lx+20}" y2="{y}" stroke="{color}" stroke-width="2"/>')
        out.append(f'<text x="{lx+24}" y="{y+4}" font-size="10">e/r={fmt_num(c["e_over_r"],2,comma=comma)}</text>')
    # axis labels
    out.append(f'<text x="{(pl+pr)/2:.1f}" y="{height-12}" font-size="12" text-anchor="middle">Top displacement [m]</text>')
    out.append(f'<text x="18" y="{(pt+pb)/2:.1f}" font-size="12" text-anchor="middle" transform="rotate(-90 18 {(pt+pb)/2:.1f})">x/H</text>')
    out.append('</svg>')
    return "\n".join(out)
