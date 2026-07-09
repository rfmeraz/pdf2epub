#!/usr/bin/env python
"""Benchmark the optional layout witness on this machine.

Times model-load + per-page (render vs predict) over a complexity-stratified
page sample and prints median / p95 / peak-RSS plus 100/300/500-page
projections — the input to the flagged-vs-`all` default decision. Reproducible
(fixed sample from the PDF), so re-run it after a transformers/torch upgrade to
catch perf regressions. Needs the ML backend installed (transformers + torch).

Usage:
    ~/pyenv/bin/python scripts/bench_layout.py books/<slug>/package [-k 8] [--dpi 150]
    ~/pyenv/bin/python scripts/bench_layout.py <file.pdf> --pages 26,50,323
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pdf2epub import layoutwitness as lw          # noqa: E402
from pdf2epub.analyze import analyze              # noqa: E402
from pdf2epub.extract import extract              # noqa: E402
from pdf2epub.initcmd import _locate_pdf          # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf_or_folder", type=Path)
    ap.add_argument("-k", type=int, default=8, help="stratified sample size")
    ap.add_argument("--pages", default=None, help="explicit spec instead of the sample")
    ap.add_argument("--dpi", type=int, default=lw.LAYOUT_DPI)
    args = ap.parse_args(argv)

    if not lw.layout_available():
        print("layout backend not installed (transformers + torch)", file=sys.stderr)
        return 1

    pdf = _locate_pdf(args.pdf_or_folder)
    doc = extract(pdf)
    a = analyze(doc)
    pages = (lw.resolve_pages(args.pages, doc, a)[0] if args.pages
             else lw.stratified_sample(doc, a, args.k))
    print(f"benchmarking {len(pages)} pages: {pages}", flush=True)

    stats = lw.benchmark(pdf, pages, args.dpi)
    print(json.dumps(stats, indent=2))
    if stats.get("page_median_s"):
        print(f"\nmedian {stats['page_median_s']}s/page, p95 {stats['page_p95_s']}s; "
              f"projected 300-page book ~{stats.get('proj_300p_min')} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
