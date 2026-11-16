"""
drift - command line batch export for the Drift Tool.

Two ways in:

  1) A project file saved by the app:

        python drift.py --project my.drift.json --out exports

  2) A plain text / CSV / TSV table pasted from SAP (floor, u[, h]):

        python drift.py --in data.txt --limit 1/500 --units-u m \
                        --out exports --name "Wind X"

     Optional per-floor heights:  --heights "1=4.2,2=3.8,3=4.2"
     or just a default:            --default-h 3.8

Output: one .svg (identical to the on-screen preview) and one .xlsx per
diagram, named after the project and the diagram.

Examples
--------
    python drift.py --in data.txt --limit 1/500 --units-u m --out out
    python drift.py --project demo.drift.json --out out --dpi 2
    python drift.py --help
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import driftcore as dc
import driftchart as ch
import driftexport as ex


def _slug(text: str | None) -> str:
    keep = []
    for c in str(text or "drift"):
        keep.append(c if (c.isalnum() or c in "-_") else "_")
    return "".join(keep)[:60] or "drift"


def _parse_heights(text: str | None) -> dict[str, float]:
    out: dict[str, float] = {}
    if not text:
        return out
    for chunk in text.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" in chunk:
            k, v = chunk.split("=", 1)
        elif ":" in chunk:
            k, v = chunk.split(":", 1)
        else:
            continue
        floor = dc.parse_number(k)
        height = dc.parse_number(v)
        if floor is None or height is None:
            raise SystemExit(f"Μη έγκυρο ύψος: {chunk!r}")
        key = str(int(floor)) if float(floor).is_integer() else str(floor)
        out[key] = height
    return out


def _read_text(path: str) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1253", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as fh:
                return fh.read()
        except UnicodeDecodeError:
            continue
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


def build_from_table(args) -> dict:
    text = _read_text(args.input)
    parsed = dc.parse_table(
        text,
        decimal=args.decimal,
        has_header=args.header,
        units_u=args.units_u,
        units_h=args.units_h,
        default_h=args.default_h,
    )
    heights = _parse_heights(args.heights)
    project = dc.new_project(args.name or os.path.splitext(os.path.basename(args.input))[0])
    model = project["models"][0]
    model["heights"] = heights
    if args.default_h:
        model["default_h"] = args.default_h
    model["base_u"] = args.base_u if args.base_u is not None else 0.0
    model["base_confirmed"] = args.base_u is not None or True

    curve = project["curves"][0]
    curve["name"] = args.name or "Καμπύλη 1"
    curve["units_u"] = args.units_u
    curve["units_h"] = args.units_h
    curve["provenance"] = args.provenance
    curve["direction"] = args.direction
    curve["case"] = args.case
    curve["rows"] = [
        {"floor": r["floor"], "u": r["u"], "h": r["h"]} for r in parsed["rows"]
    ]

    diagram = project["diagrams"][0]
    diagram["name"] = args.diagram_name or "Διάγραμμα 1"
    diagram["limit_input"] = args.limit
    diagram["limit"] = dc.parse_limit(args.limit)["value"]
    diagram["y_mode"] = args.y_mode
    diagram["x_mode"] = args.x_mode
    diagram["note"] = args.note or ""

    for issue in parsed["issues"]:
        if issue.get("level") == "error":
            print(f"  ! {issue['message']}", file=sys.stderr)
    return project


def load_project_file(path: str) -> dict:
    project = dc.load_project(path)
    project = dc.migrate(project)
    return project


def export(project: dict, out_dir: str, width: int, height: int,
           diagrams: list[str] | None = None) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    written: list[str] = []
    for diagram in project.get("diagrams", []):
        if diagrams and diagram["id"] not in diagrams and diagram.get("name") not in diagrams:
            continue
        payload = dc.diagram_payload(project, diagram)
        svg = ch.render_svg(
            payload,
            width=width,
            height=height,
            x_mode=diagram.get("x_mode", "ratio"),
            y_mode=diagram.get("y_mode", "floor"),
            show_grid=diagram.get("show_grid", True),
            legend_outside=diagram.get("legend_outside", True),
            x_min=diagram.get("x_min"),
            x_max=diagram.get("x_max"),
            note=diagram.get("note", ""),
            include_hover=False,
        )
        stem = f"{_slug(project.get('name'))[:28]}_{_slug(diagram.get('name'))[:34]}"
        svg_path = os.path.join(out_dir, stem + ".svg")
        with open(svg_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(svg)
        written.append(svg_path)

        xlsx_path = os.path.join(out_dir, stem + ".xlsx")
        ex.export_diagram(xlsx_path, project, diagram, payload)
        written.append(xlsx_path)

        issues = payload.get("issues", [])
        print(f"  {diagram.get('name')}: {len(payload.get('series', []))} καμπύλες, "
              f"{len(issues)} θέματα")
        for issue in issues[:12]:
            where = (f" · όροφος {dc.fmt_num(issue['floor'], 0)}"
                     if issue.get("floor") is not None else "")
            print(f"    - {issue.get('message')}{where}")
        if payload.get("spectral_warning"):
            print("    ! " + dc.PROVENANCE_WARNING)
    return written


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Διαγράμματα drift από SAP2000: SVG + Excel, χωρίς άνοιγμα της εφαρμογής.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    src = p.add_argument_group("είσοδος")
    src.add_argument("--project", help="αρχείο έργου .drift.json (από την εφαρμογή)")
    src.add_argument("--in", dest="input", help="αρχείο κειμένου/CSV με στήλες: όροφος, u[, h]")
    src.add_argument("--name", help="όνομα έργου / καμπύλης")
    src.add_argument("--diagram-name", help="όνομα διαγράμματος")

    prm = p.add_argument_group("δεδομένα")
    prm.add_argument("--limit", default="1/500", help="όριο: 1/500, 0,2%% ή 0,002")
    prm.add_argument("--units-u", default="mm", choices=dc.LENGTH_UNITS,
                     help="μονάδα μετακινήσεων (προεπιλογή mm)")
    prm.add_argument("--units-h", default="m", choices=dc.LENGTH_UNITS,
                     help="μονάδα υψών (προεπιλογή m)")
    prm.add_argument("--default-h", type=float, help="προεπιλεγμένο ύψος ορόφου")
    prm.add_argument("--heights", help='ύψη ανά όροφο, π.χ. "1=4.2,2=3.8"')
    prm.add_argument("--base-u", type=float, help="μετακίνηση βάσης (αν δεν υπάρχει γραμμή 0)")
    prm.add_argument("--decimal", default="auto", choices=("auto", "comma", "dot"),
                     help="δεκαδικό σύμβολο στα δεδομένα")
    prm.add_argument("--header", default="auto", choices=("auto", "yes", "no"),
                     help="η πρώτη γραμμή είναι κεφαλίδα;")
    prm.add_argument("--provenance", default="static",
                     choices=list(dc.PROVENANCE), help="προέλευση ανάλυσης")
    prm.add_argument("--direction", default="X", help="διεύθυνση (X / Y)")
    prm.add_argument("--case", default="", help="περίπτωση ανάλυσης")

    out = p.add_argument_group("έξοδος")
    out.add_argument("--out", default="drift_out", help="φάκελος εξαγωγής")
    out.add_argument("--width", type=int, default=1600, help="πλάτος SVG (px)")
    out.add_argument("--height", type=int, default=1050, help="ύψος SVG (px)")
    out.add_argument("--x-mode", default="ratio", choices=("ratio", "percent"),
                     help="άξονας Χ: δείκτης ή ποσοστό")
    out.add_argument("--y-mode", default="floor", choices=("floor", "elevation"),
                     help="άξονας Υ: όροφος ή υψόμετρο")
    out.add_argument("--note", default="", help="σημείωση κάτω από το σχήμα")
    out.add_argument("--only", nargs="*", help="εξαγωγή μόνο αυτών των διαγραμμάτων (id ή όνομα)")

    args = p.parse_args(argv)

    if not args.project and not args.input:
        p.error("δώστε --project ή --in")

    try:
        project = load_project_file(args.project) if args.project else build_from_table(args)
    except (OSError, ValueError) as exc:
        print(f"Σφάλμα: {exc}", file=sys.stderr)
        return 2

    print(f"Έργο: {project.get('name')}  ({len(project.get('diagrams', []))} διαγράμματα)")
    try:
        written = export(project, args.out, args.width, args.height, args.only)
    except Exception as exc:
        print(f"Σφάλμα εξαγωγής: {exc}", file=sys.stderr)
        return 1

    if not written:
        print("Δεν γράφτηκε κανένα αρχείο.", file=sys.stderr)
        return 1
    print(f"\nΓράφτηκαν {len(written)} αρχεία στον φάκελο {os.path.abspath(args.out)}")
    for path in written:
        print("  " + os.path.basename(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
