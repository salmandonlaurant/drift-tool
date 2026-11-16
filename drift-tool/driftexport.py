"""
driftexport - Excel workbook export (openpyxl).

One sheet per curve with input data, heights, drift columns and the two
stepped-line helper columns (X = drift, Y = level) in the document's order,
plus a summary sheet for the diagram.

Every public function accepts ``lang`` ("el" default, "en" for English sheet
names, headers and notes). The numbers follow the same language: Greek uses a
decimal comma, English a decimal dot.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from driftcore import fmt_num

HDR_FILL = PatternFill("solid", fgColor="DDE6EF")
HDR_FONT = Font(bold=True, size=10)
TITLE_FONT = Font(bold=True, size=14)
SUB_FONT = Font(italic=True, size=9, color="666666")
EXCEED_FILL = PatternFill("solid", fgColor="F8D7DA")
BASE_FILL = PatternFill("solid", fgColor="F2F2F2")
THIN = Side(style="thin", color="D9D9D9")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

TEXT = {
    "el": {
        "sheet": "Φύλλο",
        "start": "Αρχή",
        "vertical": "Κατακόρυφα",
        "right": "Οριζόντια δεξιά",
        "left": "Οριζόντια αριστερά",
        "diagonal": "Λοξά",
        "curve": "Καμπύλη",
        "direction": "Διεύθυνση",
        "case": "Περίπτωση",
        "u_units": "Μονάδες u",
        "limit": "Όριο",
        "header": ["Όροφος", "h [m]", "u [m]", "Δu [m]", "d [–]", "d [%]", "Υπέρβαση"],
        "yes": "ΝΑΙ",
        "helper": ["Σημείο", "X — Drift", "Y — Επίπεδο",
                   "Σύνδεση από προηγούμενο", "Όροφος"],
        "summary": "Σύνοψη",
        "diagram": "Διάγραμμα",
        "export_date": "Ημερομηνία εξαγωγής",
        "vertical_axis": "Κατακόρυφος άξονας",
        "floor": "Όροφος",
        "elevation": "Υψόμετρο [m]",
        "sum_header": ["Καμπύλη", "Διεύθυνση", "Περίπτωση", "Προέλευση", "Όροφοι",
                       "Έγκυρα", "Μέγιστο d", "Όροφος μέγ.", "Υπερβάσεις"],
        "notes": "Σημειώσεις",
        "spectral_note": "ΠΡΟΣΟΧΗ: υπάρχει καμπύλη φασματικής ανάλυσης. Η απλή "
                         "αφαίρεση συνδυασμένων μεγίστων δεν δίνει έγκυρο "
                         "φασματικό drift.",
        "mean": "Μέση καμπύλη",
        "diagrams_count": "Διαγράμματα",
        "proj_header": ["Διάγραμμα", "Όριο", "Καμπύλες", "Μέγιστο d",
                        "Υπερβάσεις", "Προειδοποίηση"],
        "spectral_short": "φασματική καμπύλη",
        "mean_suffix": "μέση",
        "prov": {"static": "Στατική", "timehistory": "Χρονοϊστορία", "spectrum": "Φασματική"},
    },
    "en": {
        "sheet": "Sheet",
        "start": "Start",
        "vertical": "Vertical",
        "right": "Horizontal right",
        "left": "Horizontal left",
        "diagonal": "Diagonal",
        "curve": "Curve",
        "direction": "Direction",
        "case": "Case",
        "u_units": "u units",
        "limit": "Limit",
        "header": ["Storey", "h [m]", "u [m]", "Δu [m]", "d [–]", "d [%]", "Exceeds"],
        "yes": "YES",
        "helper": ["Point", "X — Drift", "Y — Level",
                   "Connection from previous", "Storey"],
        "summary": "Summary",
        "diagram": "Diagram",
        "export_date": "Export date",
        "vertical_axis": "Vertical axis",
        "floor": "Storey",
        "elevation": "Elevation [m]",
        "sum_header": ["Curve", "Direction", "Case", "Source", "Storeys", "Valid",
                       "Max d", "Storey of max", "Exceedances"],
        "notes": "Notes",
        "spectral_note": "WARNING: a response-spectrum curve is present. Simple "
                         "subtraction of combined maxima does not give a valid "
                         "spectral drift.",
        "mean": "Mean curve",
        "diagrams_count": "Diagrams",
        "proj_header": ["Diagram", "Limit", "Curves", "Max d", "Exceedances", "Warning"],
        "spectral_short": "spectral curve",
        "mean_suffix": "mean",
        "prov": {"static": "Static", "timehistory": "Time history", "spectrum": "Response spectrum"},
    },
}


def _text(lang: str | None) -> dict[str, Any]:
    return TEXT["en"] if str(lang or "el").lower().startswith("en") else TEXT["el"]


def _comma(lang: str | None) -> bool:
    return not str(lang or "el").lower().startswith("en")


def _fmt_limit(value: float | None, lang: str | None) -> str:
    if value is None:
        return "-"
    T = _text(lang)
    comma = _comma(lang)
    inverse = (1.0 / value) if value else None
    tail = []
    if inverse:
        tail.append(f"1/{fmt_num(inverse, 0, comma=comma)}")
    tail.append(f"{fmt_num(value * 100, 3, comma=comma)}%")
    return f"{fmt_num(value, 5, comma=comma)} ({', '.join(tail)})"


def _safe_sheet(name: str, used: set[str], lang: str | None = "el") -> str:
    fallback = _text(lang)["sheet"]
    base = re.sub(r"[\[\]\:\*\?\/\\]", "-", name or fallback).strip() or fallback
    base = base[:31]
    candidate = base
    i = 2
    while candidate in used:
        suffix = f" ({i})"
        candidate = base[: 31 - len(suffix)] + suffix
        i += 1
    used.add(candidate)
    return candidate


def _connection(prev: dict[str, Any] | None, cur: dict[str, Any],
                tol: float = 1e-12, lang: str | None = "el") -> str:
    T = _text(lang)
    if prev is None:
        return T["start"]
    dx = abs(cur["x"] - prev["x"]) > tol
    dy = abs(cur["y"] - prev["y"]) > tol
    if not dx and dy:
        return T["vertical"]
    if dx and not dy:
        return T["right"] if cur["x"] > prev["x"] else T["left"]
    if not dx and not dy:
        return T["vertical"]
    return T["diagonal"]


def _write_curve_sheet(ws, curve: dict[str, Any], result: dict[str, Any],
                       diagram: dict[str, Any], limit: float | None,
                       lang: str | None = "el") -> None:
    T = _text(lang)
    ws["A1"] = curve.get("name") or T["curve"]
    ws["A1"].font = TITLE_FONT
    meta = []
    if curve.get("direction"):
        meta.append(f"{T['direction']}: {curve['direction']}")
    if curve.get("case"):
        meta.append(f"{T['case']}: {curve['case']}")
    meta.append(f"{T['u_units']}: {curve.get('units_u', 'mm')}")
    if limit is not None:
        meta.append(f"{T['limit']}: {_fmt_limit(limit, lang)}")
    ws["A2"] = "   •   ".join(meta)
    ws["A2"].font = SUB_FONT

    header = T["header"]
    row0 = 4
    for c, name in enumerate(header, start=1):
        cell = ws.cell(row=row0, column=c, value=name)
        cell.font = HDR_FONT
        cell.fill = HDR_FILL
        cell.border = BOX
        cell.alignment = Alignment(horizontal="center")

    r = row0 + 1
    for row in result.get("rows", []):
        ws.cell(row=r, column=1, value=row["floor"])
        ws.cell(row=r, column=2, value=row["h"] if row["h"] is not None else "—")
        ws.cell(row=r, column=3, value=row["u"])
        ws.cell(row=r, column=4, value=row["du"])
        ws.cell(row=r, column=5, value=row["d"])
        ws.cell(row=r, column=6, value=row["d_pct"])
        ws.cell(row=r, column=7, value=T["yes"] if row["exceeds"] else "")
        for c in range(1, 8):
            cell = ws.cell(row=r, column=c)
            cell.border = BOX
            if c in (2,):
                cell.number_format = "0.00"
            if c in (3, 4):
                cell.number_format = "0.000000"
            if c == 5:
                cell.number_format = "0.000000"
            if c == 6:
                cell.number_format = "0.000"
            if c >= 2:
                cell.alignment = Alignment(horizontal="right")
        if row.get("is_base"):
            for c in range(1, 8):
                ws.cell(row=r, column=c).fill = BASE_FILL
        if row["exceeds"]:
            for c in (5, 6, 7):
                ws.cell(row=r, column=c).fill = EXCEED_FILL
        r += 1

    # helper columns ---------------------------------------------------
    hc = 9
    for j, name in enumerate(T["helper"]):
        ws.cell(row=row0, column=hc + j, value=name)
    for c in range(hc, hc + 5):
        cell = ws.cell(row=row0, column=c)
        cell.font = HDR_FONT
        cell.fill = HDR_FILL
        cell.border = BOX
        cell.alignment = Alignment(horizontal="center")

    prev = None
    for i, p in enumerate(result.get("points", []), start=1):
        ws.cell(row=row0 + i, column=hc, value=i)
        ws.cell(row=row0 + i, column=hc + 1, value=p["x"])
        ws.cell(row=row0 + i, column=hc + 2, value=p["y"])
        ws.cell(row=row0 + i, column=hc + 3, value=_connection(prev, p, lang=lang))
        ws.cell(row=row0 + i, column=hc + 4, value=p["floor"])
        ws.cell(row=row0 + i, column=hc + 1).number_format = "0.000000"
        ws.cell(row=row0 + i, column=hc + 2).number_format = "0.00"
        for c in range(hc, hc + 5):
            ws.cell(row=row0 + i, column=c).border = BOX
        prev = p

    widths = {1: 9, 2: 9, 3: 13, 4: 13, 5: 12, 6: 10, 7: 10,
              9: 8, 10: 13, 11: 13, 12: 30, 13: 9}
    for col, w in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = w
    ws.freeze_panes = "A5"


def _write_summary(wb: Workbook, project: dict[str, Any], diagram: dict[str, Any],
                   payload: dict[str, Any], lang: str | None = "el") -> None:
    T = _text(lang)
    ws = wb.create_sheet(index=0)
    ws.title = T["summary"]
    ws["A1"] = project.get("name", "")
    ws["A1"].font = TITLE_FONT
    ws["A2"] = f"{T['diagram']}: {diagram.get('name', '')}"
    ws["A2"].font = Font(bold=True, size=11)
    ws["A3"] = f"{T['export_date']}: {_dt.datetime.now().strftime('%d/%m/%Y %H:%M')}"
    ws["A3"].font = SUB_FONT
    limit = diagram.get("limit")
    ws["A4"] = f"{T['limit']}: {diagram.get('limit_input', '')}  =  {_fmt_limit(limit, lang)}"
    ws["A4"].font = Font(size=10)
    y_mode = T["floor"] if (diagram.get("y_mode") or "floor") == "floor" else T["elevation"]
    ws["A5"] = f"{T['vertical_axis']}: {y_mode}"
    ws["A5"].font = Font(size=10)

    row = 7
    for c, name in enumerate(T["sum_header"], start=1):
        cell = ws.cell(row=row, column=c, value=name)
        cell.font = HDR_FONT
        cell.fill = HDR_FILL
        cell.border = BOX
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
    row += 1
    for s in payload.get("series", []):
        summary = s["result"]["summary"]
        values = [s["name"], "", "", T["prov"].get(s.get("provenance"), ""),
                  summary.get("n_rows"), summary.get("n_valid"),
                  summary.get("max"), summary.get("max_floor"), summary.get("n_exceed")]
        for c, v in enumerate(values, start=1):
            cell = ws.cell(row=row, column=c, value=v)
            cell.border = BOX
        ws.cell(row=row, column=7).number_format = "0.000000"
        row += 1

    row += 1
    ws.cell(row=row, column=1, value=T["notes"]).font = HDR_FONT
    row += 1
    if payload.get("spectral_warning"):
        ws.cell(row=row, column=1, value=T["spectral_note"])
        ws.cell(row=row, column=1).fill = EXCEED_FILL
        row += 1
    if diagram.get("note"):
        ws.cell(row=row, column=1, value=diagram["note"])
        row += 1

    for col, w in {1: 34, 2: 12, 3: 16, 4: 14, 5: 9, 6: 9, 7: 13, 8: 13, 9: 13}.items():
        ws.column_dimensions[get_column_letter(col)].width = w


def export_diagram(path: str, project: dict[str, Any], diagram: dict[str, Any],
                   payload: dict[str, Any], lang: str | None = "el") -> str:
    T = _text(lang)
    wb = Workbook()
    wb.remove(wb.active)
    _write_summary(wb, project, diagram, payload, lang=lang)
    used: set[str] = {T["summary"]}
    limit = diagram.get("limit")
    for s in payload.get("series", []):
        ws = wb.create_sheet(_safe_sheet(s["name"], used, lang=lang))
        curve = next((c for c in project.get("curves", []) if c["id"] == s["id"]), {})
        _write_curve_sheet(ws, curve, s["result"], diagram, limit, lang=lang)
    if payload.get("mean"):
        ws = wb.create_sheet(_safe_sheet(T["mean"], used, lang=lang))
        _write_curve_sheet(ws, {"name": T["mean"], "units_u": "m"},
                           payload["mean"], diagram, limit, lang=lang)
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    wb.save(path)
    return path


def export_project(path: str, project: dict[str, Any], payloads: list[tuple[dict, dict]],
                   lang: str | None = "el") -> str:
    """Every diagram in one workbook, one sheet per curve, prefixed by diagram."""
    T = _text(lang)
    wb = Workbook()
    wb.remove(wb.active)
    used: set[str] = set()

    ws = wb.create_sheet(T["summary"])
    used.add(T["summary"])
    ws["A1"] = project.get("name", "")
    ws["A1"].font = TITLE_FONT
    ws["A2"] = f"{T['diagrams_count']}: {len(payloads)}"
    row = 4
    for c, name in enumerate(T["proj_header"], start=1):
        cell = ws.cell(row=row, column=c, value=name)
        cell.font = HDR_FONT
        cell.fill = HDR_FILL
        cell.border = BOX
    row += 1
    for diagram, payload in payloads:
        maxima = [s["result"]["summary"]["max"] for s in payload.get("series", [])
                  if s["result"]["summary"].get("max") is not None]
        values = [diagram.get("name", ""), _fmt_limit(diagram.get("limit"), lang),
                  len(payload.get("series", [])), max(maxima) if maxima else None,
                  sum(s["result"]["summary"].get("n_exceed", 0) for s in payload.get("series", [])),
                  T["spectral_short"] if payload.get("spectral_warning") else ""]
        for c, v in enumerate(values, start=1):
            cell = ws.cell(row=row, column=c, value=v)
            cell.border = BOX
        ws.cell(row=row, column=4).number_format = "0.000000"
        row += 1
    for col, w in {1: 30, 2: 26, 3: 11, 4: 14, 5: 13, 6: 22}.items():
        ws.column_dimensions[get_column_letter(col)].width = w

    for diagram, payload in payloads:
        for s in payload.get("series", []):
            ws = wb.create_sheet(_safe_sheet(
                f"{diagram.get('name', '')} · {s['name']}", used, lang=lang))
            curve = next((c for c in project.get("curves", []) if c["id"] == s["id"]), {})
            _write_curve_sheet(ws, curve, s["result"], diagram, diagram.get("limit"),
                               lang=lang)
        if payload.get("mean"):
            ws = wb.create_sheet(_safe_sheet(
                f"{diagram.get('name', '')} · {T['mean_suffix']}", used, lang=lang))
            _write_curve_sheet(ws, {"name": T["mean"], "units_u": "m"},
                               payload["mean"], diagram, diagram.get("limit"),
                               lang=lang)
    wb.save(path)
    return path
