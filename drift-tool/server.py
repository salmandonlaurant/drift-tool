"""
Local server for the Drift Tool desktop app.

Bind: 127.0.0.1 only. The browser UI keeps the project in memory and posts it
with every request, so the server stays stateless (no half-saved state).
"""

from __future__ import annotations

import io
import os
import socket
import sys
import threading
import webbrowser

from flask import Flask, jsonify, request, send_file, send_from_directory

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import driftcore as dc
import driftchart as ch
import driftexport as ex
import outrigger as og

BASE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=os.path.join(BASE, "static"),
            template_folder=os.path.join(BASE, "templates"))
app.config["JSON_SORT_KEYS"] = False


@app.after_request
def no_cache(resp):
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.get("/")
def index():
    return send_from_directory(app.template_folder, "index.html")


def _lang(body: dict | None = None) -> str:
    """UI language: 'el' (default) or 'en'."""
    raw = None
    if isinstance(body, dict):
        raw = body.get("lang")
    if not raw:
        raw = request.args.get("lang")
    return "en" if str(raw or "el").lower().startswith("en") else "el"


@app.get("/api/bootstrap")
def bootstrap():
    lang = _lang()
    return jsonify({
        "project": dc.new_project(),
        "palette": dc.DEFAULT_PALETTE,
        "units": list(dc.LENGTH_UNITS),
        "provenance": dc.provenance(lang),
        "provenance_warning": dc.provenance_warning(lang),
        "messages": dc.messages(lang),
        "lang": lang,
        "docs_example": {
            "rows": dc.doc_example_rows(),
            "limit": "1/500",
        },
    })


def _project_from(body):
    proj = body.get("project")
    if not isinstance(proj, dict):
        raise ValueError("λείπει το project")
    return proj


@app.post("/api/normalize")
def api_normalize():
    b = request.get_json(force=True, silent=True) or {}
    try:
        return jsonify({"project": dc.migrate(_project_from(b))})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/api/demo")
def api_demo():
    path = os.path.join(BASE, "examples", "demo.drift.json")
    try:
        return jsonify({"project": dc.load_project(path)})
    except Exception as exc:
        lang = _lang()
        prefix = "demo project not found" if lang == "en" else "δεν βρέθηκε demo έργο"
        return jsonify({"error": f"{prefix}: {exc}"}), 404


@app.post("/api/parse")
def api_parse():
    b = request.get_json(force=True, silent=True) or {}
    try:
        parsed = dc.parse_table(
            b.get("text", ""),
            decimal=b.get("decimal", "auto"),
            has_header=b.get("has_header", "auto"),
            units_u=b.get("units_u", "mm"),
            units_h=b.get("units_h", "m"),
            default_h=b.get("default_h"),
        )
        return jsonify(parsed)
    except Exception as exc:  # pragma: no cover - defensive
        return jsonify({"error": str(exc)}), 400


@app.post("/api/curve")
def api_curve():
    b = request.get_json(force=True, silent=True) or {}
    try:
        proj = dc.migrate(_project_from(b))
        curve = dc.get_curve(proj, b.get("curve_id"))
        if curve is None:
            lang = _lang(b)
            return jsonify({"error": "unknown curve" if lang == "en" else "άγνωστη καμπύλη"}), 404
        limit = b.get("limit")
        if isinstance(limit, str):
            limit = dc.parse_limit(limit)["value"]
        result = dc.curve_result(proj, curve, limit, b.get("y_mode", "floor"))
        return jsonify({"result": result, "curve": curve})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/chart")
def api_chart():
    b = request.get_json(force=True, silent=True) or {}
    try:
        lang = _lang(b)
        messages = dc.messages(lang)
        proj = dc.migrate(_project_from(b))
        diagram = dc.get_diagram(proj, b.get("diagram_id")) or proj["diagrams"][0]
        payload = dc.diagram_payload(proj, diagram)
        svg = ch.render_svg(
            payload,
            width=int(b.get("width") or 940),
            height=int(b.get("height") or 620),
            x_mode=diagram.get("x_mode", "ratio"),
            y_mode=diagram.get("y_mode", "floor"),
            show_grid=diagram.get("show_grid", True),
            legend_outside=diagram.get("legend_outside", True),
            x_min=diagram.get("x_min"),
            x_max=diagram.get("x_max"),
            note=diagram.get("note", ""),
            lang=lang,
        )
        maxima = [s["result"]["summary"]["max"] for s in payload["series"]
                  if s["result"]["summary"].get("max") is not None]
        warnings = []
        if payload["spectral_warning"]:
            warnings.append(dc.provenance_warning(lang))
        seen = set()
        for s in payload["series"]:
            for issue in s["result"]["issues"]:
                key = (issue.get("code"), issue.get("floor"))
                if key in seen:
                    continue
                seen.add(key)
                text = messages.get(issue.get("code"), issue.get("message", ""))
                floor = issue.get("floor")
                if floor is not None:
                    where = (f"storey {dc.fmt_num(floor, 0, comma=False)}" if lang == "en"
                             else f"όροφος {dc.fmt_num(floor, 0)}")
                    warnings.append(f"{s['name']} · {where}: {text}")
                else:
                    warnings.append(f"{s['name']}: {text}")
        return jsonify({
            "svg": svg,
            "diagram": diagram,
            "issues": payload["issues"],
            "warnings": warnings,
            "spectral_warning": payload["spectral_warning"],
            "max": max(maxima) if maxima else None,
            "series": [{"id": s["id"], "name": s["name"],
                        "summary": s["result"]["summary"]} for s in payload["series"]],
        })
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/export/xlsx")
def api_export_xlsx():
    b = request.get_json(force=True, silent=True) or {}
    try:
        lang = _lang(b)
        en = lang == "en"
        proj = dc.migrate(_project_from(b))
        buf = io.BytesIO()
        if b.get("all"):
            payloads = [(d, dc.diagram_payload(proj, d)) for d in proj["diagrams"]]
            tmp = os.path.join(BASE, ".tmp_export.xlsx")
            ex.export_project(tmp, proj, payloads, lang=lang)
            with open(tmp, "rb") as fh:
                buf.write(fh.read())
            os.remove(tmp)
            suffix = "all" if en else "ολα"
            name = f"{_slug(proj.get('name'))}_{suffix}.xlsx"
        else:
            diagram = dc.get_diagram(proj, b.get("diagram_id")) or proj["diagrams"][0]
            payload = dc.diagram_payload(proj, diagram)
            tmp = os.path.join(BASE, ".tmp_export.xlsx")
            ex.export_diagram(tmp, proj, diagram, payload, lang=lang)
            with open(tmp, "rb") as fh:
                buf.write(fh.read())
            os.remove(tmp)
            name = f"{_slug(proj.get('name'))}_{_slug(diagram.get('name'))}.xlsx"
        buf.seek(0)
        return send_file(buf, as_attachment=True, download_name=name,
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


@app.post("/api/outrigger")
def api_outrigger():
    b = request.get_json(force=True, silent=True) or {}
    try:
        lang = _lang(b)
        params = b.get("params") or {}
        data = og.compute_all(params)
        svg1 = og.render_chart1(data, width=int(b.get("w1") or 720), height=int(b.get("h1") or 420), lang=lang)
        svg2 = og.render_chart2(data, width=int(b.get("w2") or 720), height=int(b.get("h2") or 420), lang=lang)
        return jsonify({"result": data, "svg1": svg1, "svg2": svg2})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


def _slug(text: str | None) -> str:
    keep = []
    for c in str(text or "drift"):
        keep.append(c if (c.isalnum() or c in "-_") else "_")
    return "".join(keep)[:48] or "drift"


def _free_port(start=8765, tries=25) -> int:
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return 0


def main():
    port = _free_port()
    url = f"http://127.0.0.1:{port}/"
    print(f"Drift Tool -> {url}")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
