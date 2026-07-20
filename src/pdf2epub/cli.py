"""Command-line interface: init / build / qa / corpus."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pdf2epub",
        description="Convert a print-oriented book PDF to a reflowable EPUB 3.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser(
        "init", help="Analyze a PDF; write analysis/ evidence + draft book.yaml"
    )
    p_init.add_argument("pdf_or_folder", type=Path,
                        help="The source PDF, or a package folder containing exactly one PDF")
    p_init.add_argument("--workspace", type=Path, required=True,
                        help="Per-book workspace directory")
    p_init.add_argument("--layout", action="store_true",
                        help="Run the optional ML layout witness (advisory "
                             "structure evidence into analysis/layout/; needs "
                             "transformers + torch)")
    p_init.add_argument("--layout-pages", metavar="SPEC", default=None,
                        help="Pages the layout witness scans: default 'auto' "
                             "(evidence-gated all-vs-subset); 'flagged' forces "
                             "the subset; 'all'; '+sample:N'; or '26' / "
                             "'322-336' (comma/space list)")

    p_validate = sub.add_parser(
        "validate", help="Validate a book.yaml (schema_version, required "
                         "metadata, no FILL-ME-IN) without building")
    p_validate.add_argument("config", type=Path, help="Path to book.yaml")

    p_build = sub.add_parser("build", help="Deterministic build: book.yaml -> EPUB")
    p_build.add_argument("config", type=Path, help="Path to book.yaml")
    p_build.add_argument("--dump-ir", action="store_true",
                         help="Write intermediate JSON to build/ir/")
    p_build.add_argument(
        "--upto",
        choices=["extract", "flow", "map", "images", "xhtml"],
        help="Stop after the named stage (implies --dump-ir)",
    )
    p_build.add_argument("--no-epubcheck", action="store_true",
                         help="Skip the epubcheck gate")

    p_qa = sub.add_parser("qa", help="QA harness: validate an EPUB against its source PDF")
    p_qa.add_argument("epub", type=Path)
    p_qa.add_argument("--config", type=Path, required=True, help="Path to book.yaml")
    p_qa.add_argument("--reference", type=Path,
                      help="Reference EPUB for the comparison scorecard")
    p_qa.add_argument("--visual", action="store_true",
                      help="Gate 18: sampled print-vs-EPUB contact sheets + "
                           "glyph/figure pixel checks into "
                           "build/<slug>.qa_visual/ "
                           "(informational, agent-graded)")
    p_qa.add_argument("--visual-pages", type=int, default=14, metavar="N",
                      help="Visual sample size target (clamped 6..24)")

    p_corpus = sub.add_parser(
        "corpus", help="Rebuild + QA every tracked book config (books/*/"
                       "book*.yaml minus drafts); byte-compare shipped EPUBs "
                       "and report the per-config matrix")
    p_corpus.add_argument("--books", type=Path, default=Path("books"),
                          help="Corpus root (default: books)")
    p_corpus.add_argument("--only", action="append", metavar="SLUG",
                          help="Limit to workspace dir name (or dir/stem for "
                               "a variant config); repeatable/comma lists")
    p_corpus.add_argument(
        "--upto",
        choices=["extract", "flow", "map", "images", "xhtml"],
        help="Fast probe: stop each build after this stage (bytes/QA n/a)")
    p_corpus.add_argument("--no-qa", action="store_true",
                          help="Build + byte-compare only")
    p_corpus.add_argument("--no-epubcheck", action="store_true",
                          help="Skip the epubcheck gate inside each build")
    p_corpus.add_argument("--strict", action="store_true",
                          help="Exit nonzero on any byte change (local use: "
                               "byte-compare is authoritative only on the "
                               "machine whose fonts built the shipped EPUBs)")
    p_corpus.add_argument("--json", type=Path, default=None, metavar="PATH",
                          help="Also write the matrix as JSON")
    p_corpus.add_argument("--update-baseline", action="store_true",
                          help="Write books/corpus_baseline.json from this "
                               "run's build metrics (the tracked reference "
                               "for per-rule counter deltas)")

    p_proof = sub.add_parser(
        "proofread", help="Emit reading-QA packets from the shipped EPUB "
                          "(the proofread-epub skill's desk)")
    p_proof.add_argument("epub", type=Path)
    p_proof.add_argument("--config", type=Path, required=True,
                         help="Path to book.yaml")

    p_kindle = sub.add_parser(
        "kindle", help="Convert a built EPUB to Kindle AZW3 (KF8) via Calibre "
                       "ebook-convert (post-process; the EPUB stays the source)")
    p_kindle.add_argument("epub", type=Path)
    p_kindle.add_argument("--out", type=Path, default=None,
                          help="Output path (default: <epub>.azw3)")

    p_verify = sub.add_parser(
        "verify", help="Check a built EPUB still matches its provenance "
                       "manifest (torn write / stale build)")
    p_verify.add_argument("epub", type=Path)

    p_lines = sub.add_parser(
        "lines", help="Dump RAW extraction line indexes + geometry per page "
                      "(the key for flow.overrides)")
    p_lines.add_argument("config", type=Path, help="Path to book.yaml")
    p_lines.add_argument("pages", nargs="+",
                         help="Page number(s): 47, 47-49, or comma lists")
    p_lines.add_argument("--render", action="store_true",
                         help="Also write trim-cropped page renders")
    p_lines.add_argument("--dpi", type=int, default=150)

    args = parser.parse_args(argv)

    if args.command == "init":
        from .initcmd import run_init

        return run_init(args.pdf_or_folder, args.workspace,
                        layout=args.layout, layout_pages=args.layout_pages)
    if args.command == "validate":
        from .config import ConfigError, load_config

        try:
            cfg = load_config(args.config, require_complete=True)
        except ConfigError as e:
            print(f"INVALID {args.config}: {e}")
            return 1
        print(f"OK {args.config}: schema_version {cfg.schema_version}, "
              f"title {cfg.title!r}")
        return 0
    if args.command == "build":
        from .build import run_build

        return run_build(
            args.config,
            dump_ir=args.dump_ir or bool(args.upto),
            upto=args.upto,
            epubcheck=not args.no_epubcheck,
        )
    if args.command == "qa":
        from .qa.runner import run_qa

        return run_qa(args.epub, args.config, reference=args.reference,
                      visual=args.visual, visual_pages=args.visual_pages)
    if args.command == "corpus":
        from .corpuscmd import run_corpus

        only = [t for tok in (args.only or []) for t in tok.split(",") if t]
        return run_corpus(args.books, only=only or None, upto=args.upto,
                          no_qa=args.no_qa, epubcheck=not args.no_epubcheck,
                          strict=args.strict, json_out=args.json,
                          update_baseline=args.update_baseline)
    if args.command == "proofread":
        from .proofread import run_proofread

        return run_proofread(args.epub, args.config)
    if args.command == "kindle":
        from .kindle import run_kindle

        return run_kindle(args.epub, out=args.out)
    if args.command == "verify":
        from .provenance import run_verify

        return run_verify(args.epub)
    if args.command == "lines":
        from .proofread import run_lines

        return run_lines(args.config, args.pages, render=args.render,
                         dpi=args.dpi)
    return 2


if __name__ == "__main__":
    sys.exit(main())
