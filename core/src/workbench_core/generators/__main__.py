# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Matthew Kelly
"""Command line for the generators.

    python -m workbench_core.generators import  <workbook.xlsm> -o dp.json [--report report.json]
    python -m workbench_core.generators check   <dp.json | workbook.xlsm>
    python -m workbench_core.generators build   <dp.json | workbook.xlsm> [--from N] [--upto N] [-o build.json] [--prev build.json]
    python -m workbench_core.generators diff    <old build.json> <new build.json>
    python -m workbench_core.generators export  <build.json> --gen <dp.json> [-o out.xlsx | out.csv]
    python -m workbench_core.generators golden  <folder with the five workbooks>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .check import check
from .diff import change_report
from .expand import build
from .models import BuildError, BuildResult, Generator


def _load_gen(path: str) -> Generator:
    p = Path(path)
    if p.suffix.lower() in (".xlsm", ".xlsx"):
        from .xlsx_import import import_workbook
        return import_workbook(p).generator
    return Generator.model_validate_json(p.read_text(encoding="utf-8"))


def _load_build(path: str) -> BuildResult:
    return BuildResult.model_validate_json(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m workbench_core.generators", description="Deliverable generators")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("import", help="import a generator workbook to a JSON generator")
    a.add_argument("workbook")
    a.add_argument("-o", "--out", required=True)
    a.add_argument("--report")
    a = sub.add_parser("check", help="validate (rules C1-C20)")
    a.add_argument("generator")
    a.add_argument("--all", action="store_true", help="also list INFO findings")
    a = sub.add_parser("build", help="build the output")
    a.add_argument("generator")
    a.add_argument("--from", dest="run_from", type=float)
    a.add_argument("--upto", dest="run_up_to", type=float, help="exclusive upper bound ('run below')")
    a.add_argument("--prev", help="previous build JSON (locked runs, change report)")
    a.add_argument("-o", "--out")
    a = sub.add_parser("diff", help="change report between two builds")
    a.add_argument("old")
    a.add_argument("new")
    a.add_argument("--key", default=None)
    a = sub.add_parser("export", help="export a build to .xlsx or .csv")
    a.add_argument("build")
    a.add_argument("--gen", required=True)
    a.add_argument("-o", "--out")
    a = sub.add_parser("golden", help="golden tests on a folder of workbooks (expected figures from its expected.json)")
    a.add_argument("folder")
    args = ap.parse_args(argv)

    try:
        if args.cmd == "import":
            from .xlsx_import import import_workbook
            res = import_workbook(args.workbook)
            Path(args.out).write_text(res.generator.model_dump_json(indent=1), encoding="utf-8")
            rep = res.report
            if args.report:
                Path(args.report).write_text(rep.model_dump_json(indent=2), encoding="utf-8")
            print(f"{rep.workbook}: generator {rep.generator}, {rep.runsheet_rows} runsheet rows, {rep.tags} tags, "
                  f"{rep.templates} templates ({rep.template_rows} rows), {rep.parents} parents")
            for k, n in rep.mapped_formulas.items():
                print(f"  mapped {n:5d} x {k}")
            for u in rep.unmapped_formulas:
                print(f"  UNMAPPED {u.count} x {u.formula} ({u.where})")
            for i in rep.issues:
                print(f"  issue: {i}")
            return 1 if rep.unmapped_formulas else 0
        if args.cmd == "check":
            r = check(_load_gen(args.generator))
            for f in r.findings:
                if f.severity != "INFO" or args.all:
                    print(f"{f.severity:5} {f.code:4} {f.item}: {f.detail}" + (f"  [{f.where}]" if f.where else ""))
            info = sum(1 for f in r.findings if f.severity == "INFO")
            print(f"{r.errors} errors, {sum(1 for f in r.findings if f.severity == 'WARN')} warnings, {info} info")
            return 1 if r.errors else 0
        if args.cmd == "build":
            g = _load_gen(args.generator)
            prev = _load_build(args.prev) if args.prev else None
            r = build(g, previous=prev, run_from=args.run_from, run_up_to=args.run_up_to)
            s = r.stats
            print(f"{s.processed} runs, {s.rows_written} rows ({s.output_rows} with separators), {s.non_empty_cells} cells, "
                  f"{s.no_template} without template, {r.unresolved_count} unresolved tokens, {s.duration_ms:.0f} ms")
            for w in r.warnings:
                print(f"  {w.code}: {w.item}" + (f" - {w.detail[:200]}" if w.detail else ""))
            if r.changes:
                print(f"  changes: {r.changes.added} added, {r.changes.removed} removed, {r.changes.changed} changed")
            if args.out:
                Path(args.out).write_text(r.model_dump_json(), encoding="utf-8")
            return 0
        if args.cmd == "diff":
            old, new = _load_build(args.old), _load_build(args.new)
            rep = change_report(old.header, old.rows, new.header, new.rows, args.key or "Cable Number")
            print(f"{rep.added} added, {rep.removed} removed, {rep.changed} changed")
            for e in rep.entries[:200]:
                print(f"  {e.kind:8} {e.key}" + "".join(f"\n           {c.column}: {c.old!r} -> {c.new!r}" for c in e.cells))
            return 0
        if args.cmd == "export":
            from .xlsx_export import export_csv, export_name, export_xlsx
            g = _load_gen(args.gen)
            r = _load_build(args.build)
            out = Path(args.out or export_name(g.config, g.name))
            (export_csv(r, out, g.config.date_format) if out.suffix.lower() == ".csv" else export_xlsx(r, g.config, out))
            print(out)
            return 0
        if args.cmd == "golden":
            from .golden import run_golden
            cases = run_golden(args.folder)
            if not cases:
                print("no workbooks found")
                return 1
            for c in cases:
                print(f"{'PASS' if c.passed else 'FAIL'} {c.generator:10} {c.workbook}  ({c.build_ms:.0f} ms)")
                shown = {k: c.actual[k] for k in (c.expected or c.actual)}
                print(f"     {json.dumps(shown)}" + ("  [stored Output compared]" if c.output_compared else ""))
                for f in c.failures:
                    print(f"     - {f}")
            return 0 if all(c.passed for c in cases) else 1
    except BuildError as exc:
        print(f"build error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
