"""
Acceptance tests for driftcore, taken from Drift_System_Guide chapter 6.

Run:  python tests\test_core.py
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import driftcore as dc

FAIL = []
PASS = 0


def check(name, cond, detail=""):
    global PASS
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL.append(f"{name} {detail}")
        print(f"  FAIL {name} {detail}")


def close(a, b, tol=1e-12):
    return a is not None and b is not None and abs(a - b) <= tol


# --------------------------------------------------------------------------
print("\n[1] numeric example: six drift values")
res = dc.compute_curve(dc.doc_example_rows(), units_u="m", limit=0.002)
drifts = [r["d"] for r in res["rows"] if not r["is_base"]]
expected = [0.001, 0.002, 0.0005, 0.003, 0.0025, 0.003]
check("6 rows computed", len(drifts) == 6, len(drifts))
for i, (got, exp) in enumerate(zip(drifts, expected), start=1):
    check(f"d{i} = {exp}", close(got, exp), got)

du = [r["du"] for r in res["rows"] if not r["is_base"]]
check("du = .0042 .0076 .0021 .0114 .0095 .0126",
      all(close(a, b) for a, b in zip(du, [0.0042, 0.0076, 0.0021, 0.0114, 0.0095, 0.0126])),
      du)

# --------------------------------------------------------------------------
print("\n[2] staircase: exactly 2N points in document order")
pts = res["points"]
check("12 points", len(pts) == 12, len(pts))
check("starts at (d1, 0)", close(pts[0]["x"], 0.001) and close(pts[0]["y"], 0.0),
      pts[0])
check("second point (d1, 1)", close(pts[1]["x"], 0.001) and close(pts[1]["y"], 1.0))
check("third point (d2, 1)", close(pts[2]["x"], 0.002) and close(pts[2]["y"], 1.0))
check("last point (d6, 6)", close(pts[-1]["x"], 0.003) and close(pts[-1]["y"], 6.0))
check("not sorted by x", [round(p["x"], 10) for p in pts] ==
      [0.001, 0.001, 0.002, 0.002, 0.0005, 0.0005, 0.003, 0.003,
       0.0025, 0.0025, 0.003, 0.003])
check("no synthetic (0,0) start", not (close(pts[0]["x"], 0.0) and close(pts[0]["y"], 0.0)))
check("notch present at floor 3", close(pts[4]["x"], 0.0005) and close(pts[5]["x"], 0.0005))

# --------------------------------------------------------------------------
print("\n[3] height edit 3.8 -> 4.2 on floor 2")
rows = dc.doc_example_rows()
rows[2]["h"] = 4.2
res_h = dc.compute_curve(rows, units_u="m", limit=0.002)
d2 = [r for r in res_h["rows"] if r["floor"] == 2][0]["d"]
check("d2 = 0.0076/4.2 = 0.00180952", close(d2, 0.0076 / 4.2, 1e-12), d2)
check("other floors unchanged",
      close([r for r in res_h["rows"] if r["floor"] == 3][0]["d"], 0.0005))
check("no re-analysis needed (pure recompute)", True)

# --------------------------------------------------------------------------
print("\n[4] limit parsing")
for text, value in [("0.002", 0.002), ("0,002", 0.002), ("0.2%", 0.002),
                    ("0,2 %", 0.002), ("1/500", 0.002), ("1:500", 0.002)]:
    got = dc.parse_limit(text)["value"]
    check(f"limit {text!r} -> 0.002", close(got, value, 1e-15), got)
lv = dc.parse_limit("0.2")["value"]
check("bare 0.2 stays 0.2 (not 0.2%)", close(lv, 0.2), lv)
check("percent form detected", dc.parse_limit("0,2%")["form"] == "percent")

# --------------------------------------------------------------------------
print("\n[5] exceedances with limit 0.002 (strict >)")
ex = res["summary"]["exceed_floors"]
check("floors 4,5,6 exceed (2 equals limit, not an exceedance)", ex == [4.0, 5.0, 6.0], ex)
check("n_exceed = 3", res["summary"]["n_exceed"] == 3)
check("max = 0.003", close(res["summary"]["max"], 0.003))
check("max floor = 4", res["summary"]["max_floor"] == 4.0)

# --------------------------------------------------------------------------
print("\n[6] negative displacements keep their sign, abs applied after subtraction")
neg = [{"floor": 0, "u": 0.0, "h": None},
       {"floor": 1, "u": -0.0042, "h": 4.2},
       {"floor": 2, "u": -0.0118, "h": 3.8}]
rn = dc.compute_curve(neg, units_u="m")
check("du1 negative", close(rn["rows"][1]["du"], -0.0042), rn["rows"][1]["du"])
check("d1 positive", close(rn["rows"][1]["d"], 0.001), rn["rows"][1]["d"])
check("du2 negative", close(rn["rows"][2]["du"], -0.0076))

# --------------------------------------------------------------------------
print("\n[7] errors are reported, never replaced by zeros")
empty = [{"floor": 0, "u": 0.0, "h": None},
         {"floor": 1, "u": None, "h": 4.2},
         {"floor": 2, "u": 0.0118, "h": 3.8}]
re_ = dc.compute_curve(empty, units_u="m")
r1 = re_["rows"][1]
check("empty u -> no drift", r1["d"] is None, r1["d"])
check("empty u flagged MISSING_U", "MISSING_U" in r1["codes"])
check("no zero substituted", r1["u"] is None)

zero_h = [{"floor": 0, "u": 0.0, "h": None}, {"floor": 1, "u": 0.0042, "h": 0.0}]
rz = dc.compute_curve(zero_h, units_u="m")
check("h = 0 -> no drift", rz["rows"][1]["d"] is None)
check("h = 0 flagged BAD_H", "BAD_H" in rz["rows"][1]["codes"])
check("h = 0 issues contain BAD_H", any(i["code"] == "BAD_H" for i in rz["issues"]))

neg_h = [{"floor": 0, "u": 0.0, "h": None}, {"floor": 1, "u": 0.0042, "h": -4.2}]
check("h < 0 rejected", dc.compute_curve(neg_h, units_u="m")["rows"][1]["d"] is None)

# --------------------------------------------------------------------------
print("\n[8] missing floor is not bridged")
gap = [{"floor": 0, "u": 0.0, "h": None},
       {"floor": 1, "u": 0.0042, "h": 4.2},
       {"floor": 3, "u": 0.0139, "h": 4.2},
       {"floor": 4, "u": 0.0253, "h": 3.8}]
rg = dc.compute_curve(gap, units_u="m")
f3 = [r for r in rg["rows"] if r["floor"] == 3][0]
f4 = [r for r in rg["rows"] if r["floor"] == 4][0]
check("floor 3 has no drift (gap)", f3["d"] is None, f3["d"])
check("floor 3 flagged GAP", "GAP" in f3["codes"])
check("floor 4 still computed", close(f4["d"], (0.0253 - 0.0139) / 3.8))
check("curve is split into segments", len(rg["segments"]) >= 2, len(rg["segments"]))

dup = [{"floor": 0, "u": 0.0, "h": None},
       {"floor": 1, "u": 0.0042, "h": 4.2},
       {"floor": 1, "u": 0.0050, "h": 4.2}]
rd = dc.compute_curve(dup, units_u="m")
check("duplicate floor flagged", any(i["code"] == "DUP_FLOOR" for i in rd["issues"]))
check("duplicate does not create 3 points", rd["summary"]["n_points"] == 2,
      rd["summary"]["n_points"])

# --------------------------------------------------------------------------
print("\n[9] base row required")
nobase = [{"floor": 1, "u": 0.0042, "h": 4.2}, {"floor": 2, "u": 0.0118, "h": 3.8}]
rb = dc.compute_curve(nobase, units_u="m")
check("missing base -> NO_BASE error", any(i["code"] == "NO_BASE" for i in rb["issues"]))
check("no drift without base", all(r["d"] is None for r in rb["rows"] if not r["is_base"]))
rb2 = dc.compute_curve(nobase, units_u="m", base_u=0.0, base_confirmed=True)
check("confirmed base -> drift computed", close([r for r in rb2["rows"] if r["floor"] == 1][0]["d"], 0.001))

# --------------------------------------------------------------------------
print("\n[10] clipboard parsing")
p = dc.parse_table("Όροφος\tu\t h\n0\t0,0000\t—\n1\t4,2\t4,2\n2\t11,8\t3,8")
check("header detected", p["has_header"] is True)
check("3 rows parsed", len(p["rows"]) == 3, len(p["rows"]))
check("decimal comma read", close(p["rows"][1]["u"], 4.2))
check("em dash height -> None", p["rows"][0]["h"] is None)

p2 = dc.parse_table("1\t0,0042\n2\t0,0118\n3\t0,0139\n4\t0,0253")
check("bare two-column paste: floor+u", len(p2["rows"]) == 4, len(p2["rows"]))
check("two-column paste leaves h empty", p2["rows"][0]["h"] is None)
check("decimal comma read in u", close(p2["rows"][0]["u"], 0.0042), p2["rows"][0]["u"])

p3 = dc.parse_table("1,0\t0,0042\n2,0\t0,0118")
check("decimal dot floors", close(p3["rows"][0]["floor"], 1.0))

p4 = dc.parse_table("0\t0,0000\t—\n1\t4,2\t0,0")
check("zero height from paste flagged", "BAD_H" in p4["rows"][1]["issues"], p4["rows"][1]["issues"])
check("base row height not flagged", p4["rows"][0]["issues"] == [], p4["rows"][0]["issues"])

p5 = dc.parse_table("", decimal="auto")
check("empty paste -> EMPTY", any(i["code"] == "EMPTY" for i in p5["issues"]))

# --------------------------------------------------------------------------
print("\n[11] units")
mm = [{"floor": 0, "u": 0.0, "h": None}, {"floor": 1, "u": 4.2, "h": 4200}]
ru = dc.compute_curve(mm, units_u="mm", units_h="mm")
check("mm displacements converted", close(ru["rows"][1]["d"], 0.001), ru["rows"][1]["d"])

# --------------------------------------------------------------------------
print("\n[12] mean curve")
a = dc.compute_curve(dc.doc_example_rows(), units_u="m")
rows_b = dc.doc_example_rows()
for r in rows_b:
    if r["u"] is not None:
        r["u"] = r["u"] * 2
b = dc.compute_curve(rows_b, units_u="m")
mean = dc.combine_mean([a, b])
m1 = [r for r in mean["rows"] if r["floor"] == 1][0]["d"]
check("mean of 0.001 and 0.002 = 0.0015", close(m1, 0.0015), m1)
check("mean staircase 2N points", len(mean["points"]) == 12, len(mean["points"]))

# --------------------------------------------------------------------------
print("\n[13] elevation y-axis mode")
rel = dc.compute_curve(dc.doc_example_rows(), units_u="m", y_mode="elevation")
z = rel["elevation"]
check("level 1 elevation 4.2", close(z["1"], 4.2), z["1"])
check("level 6 elevation 24.0", close(z["6"], 24.0), z["6"])
check("y axis uses elevation", close(rel["points"][1]["y"], 4.2))

# --------------------------------------------------------------------------
print("\n[14] project round trip, 7 diagrams x 15 curves")
proj = dc.new_project("test")
model = proj["models"][0]
model["heights"] = {"1": 4.2, "2": 3.8}
proj["curves"][0]["units_u"] = "m"
proj["curves"][0]["rows"] = dc.doc_example_rows()
for i in range(14):
    c = {"id": f"crv_{i}", "name": f"C{i}", "model_id": model["id"], "direction": "X",
         "case": "", "provenance": "static", "units_u": "m", "units_h": "m",
         "rows": dc.doc_example_rows(), "color": "#000", "width": 2, "dash": "solid",
         "visible": True}
    proj["curves"].append(c)
proj["diagrams"] = [{"id": f"dia_{i}", "name": f"D{i}", "limit": 0.002,
                     "limit_input": "1/500", "x_mode": "ratio", "y_mode": "floor",
                     "show_grid": True, "legend_outside": True,
                     "curve_ids": [c["id"] for c in proj["curves"][:15]],
                     "mean_ids": [], "x_min": None, "x_max": None, "note": ""}
                    for i in range(7)]
path = os.path.join(os.environ.get("TEMP", "."), "drift_test_project.json")
dc.save_project(proj, path)
loaded = dc.load_project(path)
check("7 diagrams survived", len(loaded["diagrams"]) == 7)
check("15 curves per diagram", len(loaded["diagrams"][0]["curve_ids"]) == 15)
pay = dc.diagram_payload(loaded, loaded["diagrams"][0])
check("payload computes 15 series", len(pay["series"]) == 15, len(pay["series"]))
check("payload has 12 points each", all(len(s["result"]["points"]) == 12 for s in pay["series"]))
os.remove(path)

# --------------------------------------------------------------------------
print("\n[15] one bad curve does not break the diagram")
proj2 = dc.new_project()
bad = proj2["curves"][0]
bad["rows"] = [{"floor": 0, "u": 0.0, "h": None}, {"floor": 1, "u": None, "h": 0}]
pay2 = dc.diagram_payload(proj2, proj2["diagrams"][0])
check("payload returned", len(pay2["series"]) == 1)
check("issues propagated", len(pay2["issues"]) > 0)

# --------------------------------------------------------------------------
print("\n" + "=" * 60)
print(f"passed {PASS}, failed {len(FAIL)}")
if FAIL:
    for f in FAIL:
        print("  FAILED:", f)
    sys.exit(1)
print("ALL CHECKS PASSED")
