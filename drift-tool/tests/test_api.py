"""Smoke test against the running local server (python server.py --no-browser)."""

import json
import os
import sys
import urllib.request

BASE = "http://127.0.0.1:8765"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import driftcore as dc

FAIL = []


def post(path, body):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            ctype = r.headers.get("Content-Type", "")
            if "spreadsheet" in ctype:
                return raw, r.headers
            return json.loads(raw), r.headers
    except urllib.error.HTTPError as e:
        return json.loads(e.read()), e.headers


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + ("" if cond else f"  {detail}"))
    if not cond:
        FAIL.append(name)


proj = dc.new_project("Δοκιμή")
c = proj["curves"][0]
c["name"] = "Wind-CBS"
c["units_u"] = "m"
c["rows"] = dc.doc_example_rows()
d = proj["diagrams"][0]
d["limit_input"] = "1/500"
d["limit"] = 0.002

print("\n[api] bootstrap")
with urllib.request.urlopen(BASE + "/api/bootstrap") as r:
    boot = json.loads(r.read())
check("bootstrap ok", "project" in boot)

print("\n[api] curve computation")
res, _ = post("/api/curve", {"project": proj, "curve_id": c["id"], "limit": 0.002})
rows = res["result"]["rows"]
check("6 drifts", len([r for r in rows if r["d"] is not None]) == 6, rows)
check("d4 = 0.003", abs([r for r in rows if r["floor"] == 4][0]["d"] - 0.003) < 1e-12)

print("\n[api] chart svg")
ch, _ = post("/api/chart", {"project": proj, "diagram_id": d["id"], "width": 900, "height": 560})
svg = ch.get("svg", "")
check("svg returned", svg.startswith("<svg"), svg[:60])
check("svg has a curve path", '<path d="M ' in svg)
check("limit line drawn", 'class="limit-line"' in svg)
check("legend entry present", 'Wind-CBS' in svg)
check("12 hover points", svg.count('data-phase=') == 12, svg.count('data-phase='))
check("no spectral warning", ch.get("spectral_warning") is False)
open(os.path.join(os.environ.get("TEMP", "."), "drift_api.svg"), "w", encoding="utf-8").write(svg)

print("\n[api] spectral warning")
proj2 = json.loads(json.dumps(proj))
proj2["curves"][0]["provenance"] = "spectrum"
ch2, _ = post("/api/chart", {"project": proj2, "diagram_id": d["id"], "width": 700, "height": 500})
check("spectral warning raised", ch2.get("spectral_warning") is True)
check("warning text returned", any("Φασματική" in w for w in ch2.get("warnings", [])))

print("\n[api] excel export")
xl, headers = post("/api/export/xlsx", {"project": proj, "diagram_id": d["id"]})
check("xlsx bytes", isinstance(xl, bytes) and xl[:2] == b"PK", type(xl))
path = os.path.join(os.environ.get("TEMP", "."), "drift_api.xlsx")
with open(path, "wb") as fh:
    fh.write(xl)
import openpyxl
wb = openpyxl.load_workbook(path)
check("summary sheet", "Σύνοψη" in wb.sheetnames, wb.sheetnames)
check("curve sheet", "Wind-CBS" in wb.sheetnames, wb.sheetnames)
ws = wb["Wind-CBS"]
vals = [ws.cell(row=r, column=5).value for r in range(5, 12)]
check("six drift values in sheet", all(v is not None for v in vals[1:]), vals)
check("helper X column header", ws.cell(row=4, column=10).value == "X — Drift")
check("12 helper rows", ws.cell(row=16, column=9).value == 12, ws.cell(row=16, column=9).value)

print("\n[api] all-diagrams export")
xl2, _ = post("/api/export/xlsx", {"project": proj, "all": True})
check("all export bytes", isinstance(xl2, bytes) and xl2[:2] == b"PK")

print("\n[api] normalize old file")
old = {"name": "old", "curves": [{"id": "c1", "name": "C"}], "diagrams": [], "models": []}
norm, _ = post("/api/normalize", {"project": old})
check("normalize fills defaults", norm["project"]["curves"][0]["units_u"] == "mm")

print("\n" + "=" * 50)
print(f"failed: {len(FAIL)}")
if FAIL:
    for f in FAIL:
        print("  -", f)
    sys.exit(1)
print("API SMOKE TEST PASSED")
