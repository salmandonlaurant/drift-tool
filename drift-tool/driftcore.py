"""
driftcore - engine for automatic stepped drift diagrams.

Implements the conventions of "Drift_System_Guide":

    du_i = u_i - u_(i-1)          base displacement is subtracted only at floor 1
    d_i  = |du_i| / h_i           h_i = storey height, level (i-1) -> level i

Staircase helper columns, produced per floor i in ascending order:

    (d_i, i-1)  then  (d_i, i)

so N floors give exactly 2N points.  The points are never sorted by X and no
synthetic (0, 0) start point is added.

Design rules taken from the document:
  * full precision internally, rounding only for display;
  * decimal comma and decimal point both accepted;
  * signs of the displacements preserved, absolute value applied AFTER the
    subtraction;
  * missing / zero / negative storey heights are errors, never replaced by 0;
  * non-consecutive levels are errors - a gap is never bridged;
  * a base row (floor 0) is required unless an explicitly confirmed base
    displacement is supplied;
  * limit may be entered as 0.002, 0.2% or 1/500 (same number);
  * exceedance test is strict: d_i > limit.

This module has no third-party dependencies.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Iterable, Sequence

# --------------------------------------------------------------------------
# constants
# --------------------------------------------------------------------------

UNIT_FACTORS = {"m": 1.0, "cm": 0.01, "mm": 0.001, "in": 0.0254}
LENGTH_UNITS = ("mm", "cm", "m", "in")

PROJECT_VERSION = 1

DEFAULT_PALETTE = [
    "#1f4e79", "#c00000", "#2e7d32", "#ed7d31", "#7030a0",
    "#00838f", "#c2185b", "#5d4037", "#455a64", "#9e9d24",
    "#ad1457", "#00695c", "#4527a0", "#827717", "#37474f",
]

PROVENANCE = {
    "static": "Στατική",
    "timehistory": "Χρονοϊστορία",
    "spectrum": "Φασματική",
}

PROVENANCE_WARNING = (
    "Φασματική ανάλυση: οι συνδυασμένες μέγιστες μετακινήσεις ανά όροφο δεν "
    "αρκούν για έγκυρο drift με απλή αφαίρεση. Χρειάζεται έξοδος σχετικής "
    "απόκρισης από το SAP ή κατάλληλος modal συνδυασμός."
)

PROVENANCE_EN = {
    "static": "Static",
    "timehistory": "Time history",
    "spectrum": "Response spectrum",
}

PROVENANCE_WARNING_EN = (
    "Response-spectrum analysis: combined peak displacements per storey are not "
    "enough for a valid drift by simple subtraction. Export the relative response "
    "from SAP or use an appropriate modal combination."
)

# --------------------------------------------------------------------------
# messages
# --------------------------------------------------------------------------

MSG: dict[str, str] = {
    "EMPTY": "Δεν βρέθηκαν γραμμές δεδομένων.",
    "NO_BASE": "Λείπει η γραμμή βάσης (όροφος 0). Ο πρώτος υπολογισμός απαιτεί "
               "γνωστή μετακίνηση βάσης.",
    "DUP_FLOOR": "Διπλότυπος όροφος - κρατήθηκε η πρώτη γραμμή.",
    "GAP": "Μη διαδοχικός όροφος: το drift δεν υπολογίζεται γεφυρώνοντας το κενό.",
    "MISSING_U": "Κενή ή μη αριθμητική μετακίνηση - η γραμμή δεν υπολογίζεται.",
    "MISSING_H": "Δεν υπάρχει έγκυρο ύψος ορόφου - η γραμμή δεν υπολογίζεται.",
    "BAD_H": "Μη θετικό ύψος ορόφου - η γραμμή δεν υπολογίζεται.",
    "BAD_FLOOR": "Μη αναγνωρίσιμος αριθμός ορόφου - χρησιμοποιήθηκε σειριακός "
                 "αριθμός.",
    "UNSORTED": "Οι γραμμές δεν ήταν ταξινομημένες κατά όροφο - ταξινομήθηκαν "
                "αυτόματα.",
    "EXTRA_COLUMNS": "Αγνοήθηκαν επιπλέον στήλες.",
    "LIMIT_OUT": "Το όριο βρίσκεται εκτός του εύρους του άξονα.",
    "MEAN_MISMATCH": "Οι καμπύλες δεν έχουν το ίδιο σύνολο ορόφων - ο μέσος "
                     "όρος υπολογίστηκε μόνο στους κοινούς ορόφους.",
    "NO_CURVES": "Δεν έχουν επιλεγεί καμπύλες.",
    "HEIGHT_MISMATCH": "Διαφορετικά ύψη ορόφων στο ίδιο διάγραμμα - η σύγκριση "
                       "γίνεται ως προς όροφο.",
}


MSG_EN: dict[str, str] = {
    "EMPTY": "No data rows found.",
    "NO_BASE": "The base row (storey 0) is missing. The first value needs a known "
               "base displacement.",
    "DUP_FLOOR": "Duplicate storey - the first row was kept.",
    "GAP": "Non-consecutive storey: drift is not computed across the gap.",
    "MISSING_U": "Empty or non-numeric displacement - the row is skipped.",
    "MISSING_H": "No valid storey height - the row is skipped.",
    "BAD_H": "Height is not positive - the row is skipped.",
    "BAD_FLOOR": "Unrecognised storey number - a sequential number was used.",
    "UNSORTED": "Rows were not sorted by storey - they were sorted automatically.",
    "EXTRA_COLUMNS": "Extra columns were ignored.",
    "LIMIT_OUT": "The limit is outside the axis range.",
    "MEAN_MISMATCH": "The curves do not share the same storeys - the mean was "
                     "computed on the common storeys only.",
    "NO_CURVES": "No curves selected.",
    "HEIGHT_MISMATCH": "Different storey heights in the same diagram - the "
                       "comparison is per storey.",
}


def messages(lang: str = "el") -> dict[str, str]:
    """Message dictionary for the requested UI language (default Greek)."""
    return MSG_EN if str(lang).lower().startswith("en") else MSG


def provenance(lang: str = "el") -> dict[str, str]:
    return PROVENANCE_EN if str(lang).lower().startswith("en") else PROVENANCE


def provenance_warning(lang: str = "el") -> str:
    return PROVENANCE_WARNING_EN if str(lang).lower().startswith("en") else PROVENANCE_WARNING


def msg(code: str, **kw: Any) -> str:
    text = MSG.get(code, code)
    if kw:
        text = text.format(**kw)
    return text


# --------------------------------------------------------------------------
# number / limit parsing
# --------------------------------------------------------------------------

_NUM_RE = re.compile(r"[-+]?(?:\d+(?:[.,]\d+)?|[.,]\d+)(?:[eE][-+]?\d+)?")
_THOUSANDS_RE = re.compile(r"^[-+]?\d{1,3}(?:[.,]\d{3})+$")


def parse_number(token: Any, decimal: str = "auto", thousands: str | None = None) -> float | None:
    """Parse one numeric token. Accepts decimal comma or dot, unicode minus."""
    if token is None:
        return None
    s = str(token)
    s = s.replace("\u00a0", " ").replace("\u2009", " ").replace("\u2212", "-")
    s = s.strip().replace(" ", "")
    if not s:
        return None
    s = s.replace("\u20ac", "")
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    has_dot = "." in s
    has_comma = "," in s
    if has_dot and has_comma:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif has_comma:
        if thousands == ",":
            s = s.replace(",", "")
        elif decimal == "dot":
            s = s.replace(",", "")
        elif decimal == "comma":
            s = s.replace(",", ".")
        else:  # auto: a lone comma is a decimal comma
            s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_limit(text: Any, decimal: str = "auto") -> dict[str, Any]:
    """
    Turn a limit written as 0.002, 0,2% or 1/500 into one number.

    Returns {'value': float, 'input': str, 'form': 'decimal'|'percent'|'fraction'}
    A bare 0.2 is NOT silently read as 0.2% (the document forbids that).
    Raises ValueError for unparsable input.
    """
    raw = "" if text is None else str(text).strip()
    s = raw.replace("\u00a0", " ").replace(" ", "")
    if not s:
        raise ValueError("κενό όριο")
    form = "decimal"
    if s.endswith("%"):
        form = "percent"
        s = s[:-1]
    elif "/" in s:
        form = "fraction"
        a, b = s.split("/", 1)
        num = parse_number(a, decimal)
        den = parse_number(b, decimal)
        if num is None or den is None or den == 0:
            raise ValueError(f"μη έγκυρο κλάσμα: {raw}")
        return {"value": num / den, "input": raw, "form": form}
    elif ":" in s:
        form = "fraction"
        a, b = s.split(":", 1)
        num = parse_number(a, decimal)
        den = parse_number(b, decimal)
        if num is None or den is None or den == 0:
            raise ValueError(f"μη έγκυρο κλάσμα: {raw}")
        return {"value": num / den, "input": raw, "form": form}
    value = parse_number(s, decimal)
    if value is None:
        raise ValueError(f"μη έγκυρο όριο: {raw}")
    if form == "percent":
        value = value / 100.0
    return {"value": value, "input": raw, "form": form}


def fmt_limit(value: float, extra: bool = True) -> str:
    """Human readable limit: 0.002 (1/500, 0.20%)."""
    if value is None:
        return "-"
    inverse = (1.0 / value) if value else None
    main = fmt_num(value, 5)
    if not extra:
        return main
    tail = []
    if inverse:
        tail.append(f"1/{fmt_num(inverse, 0)}")
    tail.append(f"{fmt_num(value * 100, 3)}%")
    return f"{main} ({', '.join(tail)})"


# --------------------------------------------------------------------------
# table parsing (clipboard paste)
# --------------------------------------------------------------------------

def split_lines(text: str) -> list[str]:
    return [ln for ln in re.split(r"\r\n|\r|\n", text or "") if ln.strip()]


def split_cells(line: str) -> list[str]:
    for sep in ("\t", ";", "|"):
        if sep in line:
            return [c.strip() for c in line.split(sep)]
    return [m.group(0) for m in _NUM_RE.finditer(line)]


def parse_floor(cell: Any, decimal: str = "auto") -> float | None:
    if cell is None:
        return None
    s = str(cell).strip()
    if not s:
        return None
    m = _NUM_RE.search(s)
    if not m:
        return None
    val = parse_number(m.group(0), decimal)
    if val is None:
        return None
    return val


def parse_table(
    text: str,
    *,
    decimal: str = "auto",
    thousands: str | None = None,
    has_header: str | bool = "auto",
    columns: Sequence[int] = (0, 1, 2),
    units_u: str = "mm",
    units_h: str = "m",
    default_h: float | None = None,
) -> dict[str, Any]:
    """
    Parse pasted SAP output. Rows of (floor, u[, h]) separated by tab, semicolon,
    pipe or whitespace.

    Returns {'rows': [...], 'issues': [...], 'has_header': bool}
    Row = {'floor', 'u', 'h', 'issues': [codes]}
    Missing / invalid values are kept as None - never replaced by zero.
    """
    issues: list[dict[str, Any]] = []
    lines = split_lines(text)
    if not lines:
        return {"rows": [], "issues": [{"code": "EMPTY", "level": "error",
                                        "message": msg("EMPTY")}], "has_header": False}

    c_floor, c_u, c_h = (list(columns) + [0, 1, 2])[:3]
    table = [split_cells(ln) for ln in lines]

    header = False
    if has_header == "auto":
        first = table[0]
        header = parse_floor(first[c_floor] if len(first) > c_floor else None, decimal) is None
    else:
        header = bool(has_header)
    if header:
        table = table[1:]

    rows: list[dict[str, Any]] = []
    maxcols = max((len(r) for r in table), default=0)
    if maxcols > 3:
        issues.append({"code": "EXTRA_COLUMNS", "level": "warning",
                       "message": msg("EXTRA_COLUMNS")})

    for idx, cells in enumerate(table):
        def cell(i: int) -> str | None:
            return cells[i] if len(cells) > i else None

        floor = parse_floor(cell(c_floor), decimal)
        row_issues: list[str] = []
        if floor is None:
            floor = float(idx + 1)
            row_issues.append("BAD_FLOOR")
            issues.append({"code": "BAD_FLOOR", "level": "warning",
                           "row": idx + 1, "message": msg("BAD_FLOOR")})
        u = parse_number(cell(c_u), decimal, thousands)
        h = parse_number(cell(c_h), decimal, thousands)
        if u is None:
            row_issues.append("MISSING_U")
        if floor != 0:
            if h is None and default_h is not None:
                h = default_h
            if h is None:
                row_issues.append("MISSING_H")
            elif h <= 0:
                row_issues.append("BAD_H")
        rows.append({"floor": floor, "u": u, "h": h, "issues": row_issues})

    return {"rows": rows, "issues": issues, "has_header": header}


# --------------------------------------------------------------------------
# drift computation
# --------------------------------------------------------------------------

def _sort_rows(rows: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    ordered = sorted(
        rows,
        key=lambda r: (r.get("floor") is None, r.get("floor") if r.get("floor") is not None else 0.0),
    )
    was_sorted = [r.get("floor") for r in rows] == [r.get("floor") for r in ordered]
    return ordered, not was_sorted


def compute_curve(
    rows: Sequence[dict[str, Any]],
    *,
    units_u: str = "mm",
    units_h: str = "m",
    limit: float | None = None,
    y_mode: str = "floor",
    base_u: float | None = None,
    base_confirmed: bool = False,
    decimal: str = "auto",
) -> dict[str, Any]:
    """
    Compute storey drifts and the 2N staircase points for one curve.

    rows: [{'floor': float, 'u': float|None, 'h': float|None}, ...]
          u in `units_u`, h in `units_h`.
    y_mode: 'floor'    -> Y is the floor number (document convention)
            'elevation'-> Y is the cumulative height in metres

    Result keys: rows, points, issues, summary, elevation, limits
    """
    issues: list[dict[str, Any]] = []
    fu = UNIT_FACTORS.get(units_u, 1.0)
    fh = UNIT_FACTORS.get(units_h, 1.0)

    clean: list[dict[str, Any]] = []
    for r in rows:
        floor = r.get("floor")
        if floor is None or (isinstance(floor, float) and math.isnan(floor)):
            continue
        u = r.get("u")
        h = r.get("h")
        clean.append({
            "floor": float(floor),
            "u_raw": float(u) if isinstance(u, (int, float)) else None,
            "h_raw": float(h) if isinstance(h, (int, float)) else None,
        })

    if not clean:
        return {
            "rows": [], "points": [], "elevation": {},
            "issues": issues + [{"code": "EMPTY", "level": "error", "message": msg("EMPTY")}],
            "summary": {"max": None, "max_floor": None, "n_exceed": 0, "n_rows": 0, "n_valid": 0},
        }

    ordered, unsorted = _sort_rows(clean)
    if unsorted:
        issues.append({"code": "UNSORTED", "level": "warning", "message": msg("UNSORTED")})

    # duplicates: keep first, report
    unique: list[dict[str, Any]] = []
    seen: set[float] = set()
    for r in ordered:
        if r["floor"] in seen:
            issues.append({"code": "DUP_FLOOR", "level": "error", "floor": r["floor"],
                           "message": msg("DUP_FLOOR")})
            continue
        seen.add(r["floor"])
        unique.append(r)

    # base handling -----------------------------------------------------
    has_base = unique[0]["floor"] == 0
    base_known = False
    if has_base:
        if unique[0]["u_raw"] is None:
            issues.append({"code": "MISSING_U", "level": "error", "floor": 0.0,
                           "message": msg("MISSING_U")})
        else:
            base_known = True
    else:
        if base_u is None or not base_confirmed:
            issues.append({"code": "NO_BASE", "level": "error",
                           "message": msg("NO_BASE")})
            unique.insert(0, {"floor": 0.0, "u_raw": None, "h_raw": None})
        else:
            unique.insert(0, {"floor": 0.0, "u_raw": float(base_u), "h_raw": None})
            base_known = True

    # elevation (cumulative height of each level) -----------------------
    elevation: dict[float, float] = {}
    z = 0.0
    for r in unique:
        if r["floor"] == 0:
            elevation[0.0] = 0.0
            continue
        h = r["h_raw"]
        if h is not None and h > 0:
            z += h * fh
        elevation[r["floor"]] = z

    # per-storey computation --------------------------------------------
    out_rows: list[dict[str, Any]] = []
    prev: dict[str, Any] | None = None
    for i, r in enumerate(unique):
        floor = r["floor"]
        h_raw = r["h_raw"]
        u_raw = r["u_raw"]
        codes: list[str] = []
        du = d = None

        if floor == 0:
            out_rows.append({
                "floor": 0.0, "h": None, "u": (u_raw * fu) if u_raw is not None else None,
                "du": None, "d": None, "d_pct": None, "exceeds": False,
                "ok": False, "is_base": True, "codes": [] if u_raw is not None else ["MISSING_U"],
            })
            prev = {"floor": floor, "u": u_raw * fu if u_raw is not None else None}
            continue

        if u_raw is None:
            codes.append("MISSING_U")
        if h_raw is None:
            codes.append("MISSING_H")
        elif h_raw <= 0:
            codes.append("BAD_H")

        gap = False
        if prev is not None:
            gap = abs(floor - prev["floor"] - 1.0) > 1e-9
            if gap:
                codes.append("GAP")

        if (u_raw is not None and prev is not None
                and prev.get("u") is not None and not gap):
            du = u_raw * fu - prev["u"]
        if du is not None and h_raw is not None and h_raw > 0:
            d = abs(du) / (h_raw * fh)

        ok = d is not None
        exceeds = ok and limit is not None and d > limit
        out_rows.append({
            "floor": floor,
            "h": (h_raw * fh) if h_raw is not None else None,
            "u": (u_raw * fu) if u_raw is not None else None,
            "du": du,
            "d": d,
            "d_pct": (d * 100.0) if d is not None else None,
            "exceeds": bool(exceeds),
            "ok": ok,
            "is_base": False,
            "codes": codes,
        })
        prev = {"floor": floor, "u": u_raw * fu if u_raw is not None else None}

    for r in out_rows:
        for code in r["codes"]:
            if code in ("GAP", "MISSING_U", "BAD_H", "MISSING_H"):
                issues.append({"code": code, "level": "error", "floor": r["floor"],
                               "message": msg(code)})

    # Without a known base the whole curve is not trustworthy: report it and
    # compute nothing, rather than silently starting from the second floor.
    if not base_known:
        for r in out_rows:
            if r.get("is_base"):
                continue
            r["du"] = None
            r["d"] = None
            r["d_pct"] = None
            r["exceeds"] = False
            r["ok"] = False

    # staircase points ---------------------------------------------------
    points: list[dict[str, Any]] = []
    breaks: list[int] = []
    for r in out_rows:
        if r["d"] is None:
            continue
        floor = r["floor"]
        if r.get("is_base"):
            continue
        y0 = 0.0 if y_mode == "elevation" else floor - 1.0
        y1 = elevation.get(floor, floor) if y_mode == "elevation" else floor
        points.append({"x": r["d"], "y": y0, "floor": floor, "phase": "in"})
        points.append({"x": r["d"], "y": y1, "floor": floor, "phase": "out"})

    # contiguous segments (gaps in the data break the polyline)
    segments: list[list[dict[str, Any]]] = []
    cur: list[dict[str, Any]] = []
    last_floor = None
    for p in points:
        if last_floor is not None and p["floor"] - last_floor > 1.0 + 1e-9:
            if cur:
                segments.append(cur)
            cur = []
        cur.append(p)
        last_floor = p["floor"]
    if cur:
        segments.append(cur)

    valid = [r for r in out_rows if r["d"] is not None]
    max_row = max(valid, key=lambda r: r["d"]) if valid else None
    summary = {
        "max": max_row["d"] if max_row else None,
        "max_floor": max_row["floor"] if max_row else None,
        "n_exceed": sum(1 for r in valid if r["exceeds"]),
        "exceed_floors": [r["floor"] for r in valid if r["exceeds"]],
        "n_rows": len(out_rows) - 1,
        "n_valid": len(valid),
        "n_points": len(points),
        "limit": limit,
    }
    return {
        "rows": out_rows,
        "points": points,
        "segments": segments,
        "elevation": {
            (str(int(k)) if float(k).is_integer() else str(k)): v
            for k, v in elevation.items()
        },
        "issues": issues,
        "summary": summary,
    }


# --------------------------------------------------------------------------
# mean curve
# --------------------------------------------------------------------------

def combine_mean(results: Sequence[dict[str, Any]], *, y_mode: str = "floor") -> dict[str, Any]:
    """
    Mean of several computed curves: drift per curve first, mean per floor
    second, staircase coordinates last (never the other way round).
    """
    issues: list[dict[str, Any]] = []
    if not results:
        return {"rows": [], "points": [], "segments": [], "issues": [{"code": "NO_CURVES",
                "level": "warning", "message": msg("NO_CURVES")}],
                "summary": {"max": None, "max_floor": None, "n_exceed": 0, "n_rows": 0, "n_valid": 0}}

    per_floor: dict[float, list[float]] = {}
    heights: dict[float, list[float]] = {}
    sets = []
    for res in results:
        floors = set()
        for r in res.get("rows", []):
            if r.get("is_base"):
                continue
            floors.add(r["floor"])
            if r.get("d") is not None:
                per_floor.setdefault(r["floor"], []).append(r["d"])
            if r.get("h") is not None:
                heights.setdefault(r["floor"], []).append(r["h"])
        sets.append(floors)
    if len(set(frozenset(s) for s in sets)) > 1:
        issues.append({"code": "MEAN_MISMATCH", "level": "warning", "message": msg("MEAN_MISMATCH")})

    out_rows = [{"floor": 0.0, "h": None, "u": None, "du": None, "d": None, "d_pct": None,
                 "exceeds": False, "ok": False, "is_base": True, "codes": []}]
    for floor in sorted(per_floor):
        values = per_floor[floor]
        d = sum(values) / len(values) if values else None
        hvals = heights.get(floor, [])
        out_rows.append({
            "floor": floor,
            "h": (sum(hvals) / len(hvals)) if hvals else None,
            "u": None, "du": None,
            "d": d, "d_pct": (d * 100.0) if d is not None else None,
            "exceeds": False, "ok": d is not None, "is_base": False, "codes": [],
        })

    points: list[dict[str, Any]] = []
    for r in out_rows:
        if r["d"] is None or r.get("is_base"):
            continue
        f = r["floor"]
        points.append({"x": r["d"], "y": (f - 1.0), "floor": f, "phase": "in"})
        points.append({"x": r["d"], "y": f, "floor": f, "phase": "out"})

    valid = [r for r in out_rows if r["d"] is not None]
    max_row = max(valid, key=lambda r: r["d"]) if valid else None
    return {
        "rows": out_rows,
        "points": points,
        "segments": [points] if points else [],
        "elevation": {},
        "issues": issues,
        "summary": {"max": max_row["d"] if max_row else None,
                    "max_floor": max_row["floor"] if max_row else None,
                    "n_exceed": 0, "exceed_floors": [],
                    "n_rows": len(out_rows) - 1, "n_valid": len(valid),
                    "n_points": len(points), "limit": None},
    }


# --------------------------------------------------------------------------
# project model
# --------------------------------------------------------------------------

def new_id(prefix: str) -> str:
    import uuid
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def new_project(name: str = "Νέο έργο") -> dict[str, Any]:
    model_id = new_id("mdl")
    curve_id = new_id("crv")
    diagram_id = new_id("dia")
    return {
        "version": PROJECT_VERSION,
        "name": name,
        "models": [{
            "id": model_id,
            "name": "Μοντέλο 1",
            "default_h": 3.8,
            "heights": {},          # {"floor": height}
            "base_u": 0.0,
            "base_confirmed": True,
        }],
        "curves": [{
            "id": curve_id,
            "name": "Καμπύλη 1",
            "model_id": model_id,
            "direction": "X",
            "case": "",
            "provenance": "static",
            "units_u": "mm",
            "units_h": "m",
            "rows": [],
            "color": DEFAULT_PALETTE[0],
            "width": 2.0,
            "dash": "solid",
            "visible": True,
        }],
        "diagrams": [{
            "id": diagram_id,
            "name": "Διάγραμμα 1",
            "limit_input": "1/500",
            "limit": 0.002,
            "x_mode": "ratio",
            "y_mode": "floor",
            "show_grid": True,
            "legend_outside": True,
            "curve_ids": [curve_id],
            "mean_ids": [],
            "x_min": None,
            "x_max": None,
            "note": "",
        }],
        "active_diagram": diagram_id,
        "active_curve": curve_id,
    }


def get_model(project: dict[str, Any], model_id: str | None) -> dict[str, Any] | None:
    for m in project.get("models", []):
        if m["id"] == model_id:
            return m
    return None


def get_curve(project: dict[str, Any], curve_id: str) -> dict[str, Any] | None:
    for c in project.get("curves", []):
        if c["id"] == curve_id:
            return c
    return None


def get_diagram(project: dict[str, Any], diagram_id: str) -> dict[str, Any] | None:
    for d in project.get("diagrams", []):
        if d["id"] == diagram_id:
            return d
    return None


def curve_result(project: dict[str, Any], curve: dict[str, Any], limit: float | None,
                 y_mode: str = "floor") -> dict[str, Any]:
    model = get_model(project, curve.get("model_id")) or {}
    rows = [dict(r) for r in curve.get("rows", [])]
    # fill missing heights from the model height table
    heights = model.get("heights", {}) or {}
    default_h = model.get("default_h")
    for r in rows:
        if r.get("h") is None and r.get("floor") is not None:
            key = str(int(r["floor"])) if float(r["floor"]).is_integer() else str(r["floor"])
            if key in heights:
                r["h"] = heights[key]
            elif float(r["floor"]) != 0 and default_h:
                r["h"] = default_h
    base_u = model.get("base_u")
    return compute_curve(
        rows,
        units_u=curve.get("units_u", "mm"),
        units_h=curve.get("units_h", "m"),
        limit=limit,
        y_mode=y_mode,
        base_u=base_u,
        base_confirmed=bool(model.get("base_confirmed", False)),
    )


def diagram_payload(project: dict[str, Any], diagram: dict[str, Any]) -> dict[str, Any]:
    """Compute every curve of a diagram plus metadata for the chart renderer."""
    limit = diagram.get("limit")
    series = []
    spectra = False
    for cid in diagram.get("curve_ids", []):
        curve = get_curve(project, cid)
        if not curve:
            continue
        res = curve_result(project, curve, limit, diagram.get("y_mode", "floor"))
        if curve.get("provenance") == "spectrum":
            spectra = True
        series.append({
            "id": curve["id"],
            "name": curve.get("name", ""),
            "color": curve.get("color"),
            "width": curve.get("width", 2.0),
            "dash": curve.get("dash", "solid"),
            "visible": curve.get("visible", True),
            "provenance": curve.get("provenance", "static"),
            "result": res,
        })
    mean = None
    if diagram.get("mean_ids"):
        picked = [s for s in series if s["id"] in diagram["mean_ids"]]
        if picked:
            mean = combine_mean([p["result"] for p in picked], y_mode=diagram.get("y_mode", "floor"))
    return {
        "diagram": diagram,
        "series": series,
        "mean": mean,
        "issues": [i for s in series for i in s["result"]["issues"]],
        "spectral_warning": spectra,
    }


# --------------------------------------------------------------------------
# formatting helpers (Greek locale)
# --------------------------------------------------------------------------

def fmt_num(value: Any, decimals: int = 4, comma: bool = True) -> str:
    if value is None:
        return "-"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isnan(v) or math.isinf(v):
        return "-"
    s = f"{v:.{decimals}f}"
    if s == "-0" or s.startswith("-0.") and float(s) == 0:
        s = s[1:]
    if comma:
        s = s.replace(".", ",")
    return s


def smart_fmt(value: float, scale: float = 1.0) -> str:
    """Trim trailing zeros but keep at least 3 significant decimals."""
    if value is None:
        return "-"
    v = value * scale
    for dec in (3, 4, 5, 6):
        s = f"{v:.{dec}f}"
        if float(s) != 0 and abs(float(s) - v) < abs(v) * 1e-3:
            break
    return s.replace(".", ",")


def nice_ticks(lo: float, hi: float, target: int = 6) -> list[float]:
    if hi <= lo:
        hi = lo + (abs(lo) if lo else 1.0)
    raw = (hi - lo) / max(1, target)
    mag = 10 ** math.floor(math.log10(raw)) if raw > 0 else 1
    for m in (1, 2, 2.5, 5, 10):
        step = m * mag
        if raw <= step:
            break
    start = math.floor(lo / step) * step
    ticks = []
    v = start
    guard = 0
    while v <= hi + step * 1e-9 and guard < 1000:
        if v >= lo - step * 1e-9:
            ticks.append(round(v, 12))
        v += step
        guard += 1
    return ticks


# --------------------------------------------------------------------------
# JSON project io
# --------------------------------------------------------------------------

def save_project(project: dict[str, Any], path: str) -> None:
    data = json.dumps(project, ensure_ascii=False, indent=2)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(data)


def load_project(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return migrate(data)


def migrate(data: dict[str, Any]) -> dict[str, Any]:
    """Fill missing keys so older files keep working."""
    base = new_project()
    data.setdefault("version", PROJECT_VERSION)
    data.setdefault("name", base["name"])
    for key in ("models", "curves", "diagrams"):
        data.setdefault(key, [])
    for m in data["models"]:
        m.setdefault("default_h", 3.8)
        m.setdefault("heights", {})
        m.setdefault("base_u", 0.0)
        m.setdefault("base_confirmed", True)
    for c in data["curves"]:
        c.setdefault("rows", [])
        c.setdefault("units_u", "mm")
        c.setdefault("units_h", "m")
        c.setdefault("color", DEFAULT_PALETTE[0])
        c.setdefault("width", 2.0)
        c.setdefault("dash", "solid")
        c.setdefault("visible", True)
        c.setdefault("provenance", "static")
    for d in data["diagrams"]:
        d.setdefault("limit", 0.002)
        d.setdefault("limit_input", "1/500")
        d.setdefault("x_mode", "ratio")
        d.setdefault("y_mode", "floor")
        d.setdefault("show_grid", True)
        d.setdefault("legend_outside", True)
        d.setdefault("curve_ids", [])
        d.setdefault("mean_ids", [])
    if data["curves"] and data.get("active_curve") not in [c["id"] for c in data["curves"]]:
        data["active_curve"] = data["curves"][0]["id"]
    if data["diagrams"] and data.get("active_diagram") not in [d["id"] for d in data["diagrams"]]:
        data["active_diagram"] = data["diagrams"][0]["id"]
    return data


# --------------------------------------------------------------------------
# self-check: the worked example of the document
# --------------------------------------------------------------------------

DOC_EXAMPLE_U = [0.0, 0.0042, 0.0118, 0.0139, 0.0253, 0.0348, 0.0474]
DOC_EXAMPLE_H = [None, 4.2, 3.8, 4.2, 3.8, 3.8, 4.2]
DOC_EXPECTED_D = [0.001, 0.002, 0.0005, 0.003, 0.0025, 0.003]


def doc_example_rows() -> list[dict[str, Any]]:
    return [{"floor": float(i), "u": u, "h": h}
            for i, (u, h) in enumerate(zip(DOC_EXAMPLE_U, DOC_EXAMPLE_H))]


if __name__ == "__main__":
    res = compute_curve(doc_example_rows(), units_u="m", limit=0.002)
    for r in res["rows"]:
        print(f"{r['floor']:>4.0f}  h={fmt_num(r['h'],2)}  u={fmt_num(r['u'],4)}  "
              f"du={fmt_num(r['du'],4)}  d={fmt_num(r['d'],4)}  "
              f"{'EXCEEDS' if r['exceeds'] else ''}")
    print("points:", res["summary"]["n_points"])
    print("max:", res["summary"]["max"], "floor", res["summary"]["max_floor"])
