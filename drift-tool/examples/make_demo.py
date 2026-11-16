"""
Build the example project and a small paste-in table.

All numbers are SYNTHETIC - they illustrate the shape of a real diagram, they
are not measurements.  Run:

    python examples/make_demo.py
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import driftcore as dc

FLOORS = 14
HEIGHTS = {str(i): (3.8 if i % 2 else 4.2) for i in range(1, FLOORS + 1)}
HEIGHT_SEQ = [HEIGHTS[str(i)] for i in range(1, FLOORS + 1)]


def rows_from_drift(profile, units_u="mm", units_h="m"):
    """Turn a list of target drifts (one per storey) into displacement rows."""
    rows = [{"floor": 0.0, "u": 0.0, "h": None}]
    u = 0.0
    f = 1.0  # metres
    for d, h in zip(profile, HEIGHT_SEQ):
        du = d * h
        # store in mm, rounded like SAP output
        u = round((u + du) * 1000.0, 4) / 1000.0
        rows.append({"floor": f, "u": round(u * 1000.0, 1), "h": h})
        f += 1.0
    return rows


def profile(kind: str, scale: float) -> list[float]:
    out = []
    for i in range(1, FLOORS + 1):
        t = i / FLOORS
        if kind == "wind":
            d = (0.00055 + 0.00145 * t ** 1.6) * scale
        elif kind == "quake":
            d = (0.0015 + 0.0011 * t) * scale * (1.0 + 0.25 * (t - 0.45) ** 2)
        else:  # outrigger variants: same quake shape, shifted down
            d = (0.0009 + 0.0017 * (1.0 - abs(t - 0.62) * 1.5)) * scale
        out.append(round(d, 7))
    return out


CURVES = [
    # name, kind, scale, colour, dash, direction, case, note
    ("Wind-CBS", "wind", 1.00, "#1f4e79", "solid", "X", "WIND +X", "Κτίριο αναφοράς"),
    ("Wind-BIE", "wind", 1.12, "#c00000", "dash", "Y", "WIND +Y", "Παραλλαγή B"),
    ("Earthquake-CSB", "quake", 1.00, "#2e7d32", "solid", "X", "EQ +X", "Φάσμα σχεδιασμού"),
    ("Earthquake-BIE", "quake", 1.08, "#ed7d31", "dash", "Y", "EQ +Y", "Φάσμα σχεδιασμού"),
    ("Outrigger 1", "outrigger", 0.95, "#7030a0", "solid", "X", "EQ +X", "Outrigger 1"),
    ("Outrigger 2", "outrigger", 0.90, "#00838f", "longdash", "X", "EQ +X", "Outrigger 2"),
    ("Outrigger 3", "outrigger", 0.86, "#c2185b", "dashdot", "X", "EQ +X", "Outrigger 3"),
]

WIDTHS = [2.0, 2.0, 2.4, 2.4, 2.0, 2.0, 2.0]


def main() -> None:
    project = dc.new_project("Παράδειγμα – σύνθετα δεδομένα")
    project["name"] = "Παράδειγμα – σύνθετα δεδομένα (όχι πραγματικά)"
    model = project["models"][0]
    model["name"] = "Κτίριο 14 ορόφων"
    model["default_h"] = 4.0
    model["heights"] = dict(HEIGHTS)
    model["base_u"] = 0.0
    model["base_confirmed"] = True

    project["curves"] = []
    for i, (name, kind, scale, color, dash, direction, case, note) in enumerate(CURVES):
        project["curves"].append({
            "id": f"crv_demo_{i}",
            "name": name,
            "model_id": model["id"],
            "direction": direction,
            "case": case,
            "provenance": "static",
            "units_u": "mm",
            "units_h": "m",
            "rows": rows_from_drift(profile(kind, scale)),
            "color": color,
            "width": WIDTHS[i],
            "dash": dash,
            "visible": True,
            "note": note,
        })

    ids = [c["id"] for c in project["curves"]]
    project["diagrams"] = [
        {
            "id": "dia_demo_1",
            "name": "Άνεμος & Σεισμός",
            "limit_input": "1/500",
            "limit": 0.002,
            "x_mode": "ratio",
            "y_mode": "floor",
            "show_grid": True,
            "legend_outside": True,
            "curve_ids": ids[0:4],
            "mean_ids": [ids[0], ids[1]],
            "x_min": None,
            "x_max": None,
            "note": "Συνθετικά δεδομένα για επίδειξη. Χωρίς απαίτηση πραγματικών μετρήσεων.",
        },
        {
            "id": "dia_demo_2",
            "name": "Θέσεις outrigger",
            "limit_input": "1/400",
            "limit": 0.0025,
            "x_mode": "ratio",
            "y_mode": "floor",
            "show_grid": True,
            "legend_outside": True,
            "curve_ids": ids[2:7],
            "mean_ids": [],
            "x_min": None,
            "x_max": None,
            "note": "Σύγκριση τριών θέσεων outrigger – και πάλι συνθετικά δεδομένα.",
        },
        {
            "id": "dia_demo_3",
            "name": "Όλες οι καμπύλες",
            "limit_input": "0,2%",
            "limit": 0.002,
            "x_mode": "percent",
            "y_mode": "floor",
            "show_grid": True,
            "legend_outside": True,
            "curve_ids": ids,
            "mean_ids": [],
            "x_min": None,
            "x_max": None,
            "note": "Ίδια δεδομένα με ποσοστιαίο άξονα.",
        },
    ]
    project["active_diagram"] = "dia_demo_1"
    project["active_curve"] = ids[0]

    out_json = os.path.join(HERE, "demo.drift.json")
    with open(out_json, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(project, ensure_ascii=False, indent=2))

    # a small paste-in table (same first curve, tab separated)
    table = ["Όροφος\tu [mm]\th [m]"]
    for r in project["curves"][0]["rows"]:
        table.append(
            f"{int(r['floor'])}\t{dc.fmt_num(r['u'], 1)}\t"
            + ("—" if r["h"] is None else dc.fmt_num(r["h"], 2))
        )
    with open(os.path.join(HERE, "wind-cbs.tsv"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(table) + "\n")

    print("wrote", out_json)
    print("wrote", os.path.join(HERE, "wind-cbs.tsv"))
    # sanity check
    res = dc.curve_result(project, project["curves"][0], 0.002)
    print("curve 1 max drift:", dc.fmt_num(res["summary"]["max"], 6),
          "on floor", dc.fmt_num(res["summary"]["max_floor"], 0))


if __name__ == "__main__":
    main()
